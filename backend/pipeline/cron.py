from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.models import DiscoveredSource, Lead, Strategy, SyncRun

log = logging.getLogger(__name__)


def now() -> datetime:
    return datetime.now(timezone.utc)


def dedupe_check(db: Session, user_id: int, source: str, external_id: str) -> bool:
    return db.query(Lead).filter(
        Lead.user_id == user_id,
        Lead.source == source,
        Lead.external_id == str(external_id),
    ).first() is not None


def save_lead(db: Session, strategy: Strategy, source: str, enriched: dict, scored: dict) -> Lead | None:
    try:
        lead = Lead(
            user_id=strategy.user_id,
            strategy_id=strategy.id,
            source=source,
            external_id=str(enriched.get("external_id", "")),
            person_name=enriched.get("person_name", "Unknown"),
            person_title=enriched.get("person_title"),
            person_location=enriched.get("person_location"),
            person_linkedin_url=enriched.get("person_linkedin_url"),
            person_github_url=enriched.get("person_github_url"),
            person_twitter_url=enriched.get("person_twitter_url"),
            person_email=enriched.get("person_email"),
            email_verified=enriched.get("email_verified", False),
            email_source=enriched.get("email_source"),
            email_confidence=enriched.get("email_confidence", 0.0),
            person_phone=enriched.get("person_phone"),
            phone_source=enriched.get("phone_source"),
            source_url=enriched.get("source_url"),
            source_profile_url=enriched.get("source_profile_url"),
            source_snippet=enriched.get("source_snippet"),
            company_name=enriched.get("company_name"),
            company_domain=enriched.get("company_domain"),
            company_size=enriched.get("company_size"),
            company_industry=enriched.get("company_industry"),
            intent_score=scored.get("intent_score", 0.0),
            intent_signals=scored.get("intent_signals", []),
            raw_data={
                **(enriched.get("raw_data") or {}),
                # Proof-of-intent payload — surfaced in the lead drawer
                "matched_phrases": scored.get("matched_phrases", []),
                "matched_keywords": scored.get("matched_keywords", []),
                "ai_summary": scored.get("ai_summary", ""),
                "signal_label": scored.get("signal_label", ""),
            },
        )
        db.add(lead)
        db.commit()
        return lead
    except IntegrityError:
        db.rollback()
        return None


def resolve_url_pattern(pattern: str, strategy: Strategy) -> str:
    url = pattern
    for var, val in [
        ("{role}", (strategy.target_roles or [""])[0]),
        ("{location}", (strategy.target_locations or [""])[0]),
        ("{keyword}", (strategy.keywords or [""])[0]),
    ]:
        url = url.replace(var, val)
    return url


def _run_discovered_source(ds: DiscoveredSource, strategy: Strategy, db: Session) -> None:
    from backend.pipeline.universal_extractor import extract_leads_from_url
    from backend.pipeline.scorer import score_lead_smart
    from backend.enrichment.email import enrich_lead

    url = resolve_url_pattern(ds.url_pattern, strategy)
    raw_leads = extract_leads_from_url(url, strategy)
    ds.runs += 1
    ds.last_run_at = now()
    saved = 0

    for raw in raw_leads:
        ext_id = raw.get("person_email") or raw.get("person_linkedin_url") or raw.get("person_name", "")
        if not ext_id or dedupe_check(db, strategy.user_id, f"discovered:{ds.name}", ext_id):
            continue
        raw["external_id"] = ext_id
        # Tag every discovered lead with where it came from
        raw.setdefault("source_url", url)
        raw.setdefault("source_profile_url", raw.get("person_linkedin_url") or url)
        if not raw.get("source_snippet") and raw.get("context"):
            raw["source_snippet"] = f"Found on {ds.name}\n{url}\n\n{raw['context']}"
        if not cheap_relevance(raw, strategy.raw_icp_params):
            continue
        enriched = enrich_lead(raw)
        if not has_contact(enriched):
            continue
        scored = score_lead_smart(enriched, strategy)
        if scored["intent_score"] >= strategy.intent_threshold:
            save_lead(db, strategy, f"discovered:{ds.name}", enriched, scored)
            saved += 1

    ds.leads_found_total += saved
    ds.success_rate = ds.leads_found_total / max(ds.runs, 1)
    ds.last_error = None

    if ds.runs > 3 and ds.leads_found_total == 0:
        ds.status = "broken"
        log.info(f"Marking discovered source {ds.name} as broken (0 leads in {ds.runs} runs)")

    # Auto-delete persistently broken sources to stop monitor-table pollution
    if ds.runs >= 5 and ds.leads_found_total == 0 and ds.status == "broken":
        log.info(f"Auto-deleting broken discovered source {ds.name} ({ds.runs} runs, 0 leads)")
        db.delete(ds)

    db.commit()


def is_first_run_of_week() -> bool:
    return datetime.now(timezone.utc).weekday() == 0 and datetime.now(timezone.utc).hour < 2


def has_contact(enriched: dict) -> bool:
    """Return True if the lead has at least one way to reach them.

    Required to save a lead — prevents useless nameless rows with no outreach path.
    Accepted contact fields (any one is enough):
      - person_email
      - person_linkedin_url
      - person_github_url
      - person_twitter_url
      - source_profile_url  (platform profile: Reddit /u/, HN user, SO user, etc.)
    """
    return bool(
        enriched.get("person_email")
        or enriched.get("person_linkedin_url")
        or enriched.get("person_github_url")
        or enriched.get("person_twitter_url")
        or enriched.get("source_profile_url")
    )


def cheap_relevance(raw: dict, icp: dict) -> bool:
    """Free heuristic — does this lead share ANY signal with the ICP?

    Skips the expensive LLM scoring call for obviously-irrelevant leads,
    conserving the Groq daily token budget. Returns True if worth LLM-scoring.
    """
    if not icp:
        return True  # no ICP params yet — let it through
    # Build the lead's text blob
    rd = raw.get("raw_data") or {}
    blob = " ".join(str(x) for x in [
        raw.get("person_name", ""), raw.get("person_title", ""),
        raw.get("company_name", ""), raw.get("source_snippet", ""),
        rd.get("bio", ""), rd.get("context", ""),
    ]).lower()
    if not blob.strip():
        return True  # no content to judge — let the LLM decide

    # Collect ICP signal terms (single words ≥3 chars)
    terms: set[str] = set()
    for key in ("buyer_intent_keywords", "target_industries", "industries", "target_roles", "tech_keywords"):
        for phrase in (icp.get(key) or []):
            for w in str(phrase).lower().split():
                if len(w) >= 3:
                    terms.add(w)
    if not terms:
        return True
    # Relevant if the lead's blob contains at least one ICP term
    return any(t in blob for t in terms)


def sync_strategy(strategy_id: int, source_names: list[str] | None = None, per_source_limit: int = 30) -> dict:
    """Run base sources for a single strategy. Returns a summary dict.

    `source_names` filters which BASE_SOURCES to run. None = all.
    `per_source_limit` caps leads per source (lower = faster manual triggers).
    """
    from backend.database import SessionLocal
    from backend.enrichment.email import enrich_lead
    from backend.pipeline.scorer import score_lead_smart
    import backend.sources as sources_pkg

    db = SessionLocal()
    summary: dict = {"strategy_id": strategy_id, "sources": {}}
    try:
        strategy = db.get(Strategy, strategy_id)
        if not strategy:
            return {**summary, "error": "strategy not found"}

        # Source selection priority:
        # 1. Explicit override (source_names param from API call)
        # 2. Per-strategy recommended_sources from ICP translator
        # 3. Global INTENT_SOURCES fallback
        if source_names:
            modules = [m for m in sources_pkg.BASE_SOURCES if m.NAME in source_names]
        else:
            rec = (strategy.raw_icp_params or {}).get("recommended_sources") or []
            if rec:
                modules = [m for m in sources_pkg.BASE_SOURCES if m.NAME in rec]
                if not modules:
                    modules = sources_pkg.INTENT_SOURCES
            else:
                modules = sources_pkg.INTENT_SOURCES

        log.info(f"[sync_strategy] strategy={strategy_id} sources={[m.NAME for m in modules]}")

        for source_module in modules:
            run = SyncRun(strategy_id=strategy.id, source=source_module.NAME, status="running", started_at=now())
            db.add(run)
            db.commit()
            saved = 0
            try:
                raw_leads = source_module.fetch(strategy.raw_icp_params, limit=per_source_limit)
                for raw in raw_leads:
                    if dedupe_check(db, strategy.user_id, source_module.NAME, raw.get("external_id", "")):
                        continue
                    # Cheap pre-filter — skip LLM scoring for irrelevant leads (saves tokens)
                    if not cheap_relevance(raw, strategy.raw_icp_params):
                        continue
                    enriched = enrich_lead(raw)
                    # Must have at least one reachable contact before scoring
                    if not has_contact(enriched):
                        continue
                    scored = score_lead_smart(enriched, strategy)
                    if scored["intent_score"] >= strategy.intent_threshold:
                        if save_lead(db, strategy, source_module.NAME, enriched, scored):
                            saved += 1
                run.leads_found = saved
                run.status = "ok"
                summary["sources"][source_module.NAME] = {"status": "ok", "saved": saved, "fetched": len(raw_leads)}
                log.info(f"[sync_strategy] {source_module.NAME}: fetched={len(raw_leads)} saved={saved}")
            except Exception as e:
                run.status = "error"
                run.error = str(e)
                summary["sources"][source_module.NAME] = {"status": "error", "error": str(e)}
                log.error(f"[sync_strategy] {source_module.NAME} failed: {e}")
            finally:
                run.finished_at = now()
                db.commit()

        # ── Run discovered sources too (they're often the ONLY relevant sources
        # for non-tech ICPs). And if none exist yet, kick off discovery so the
        # next sync has niche sources to scrape.
        try:
            discovered = (
                db.query(DiscoveredSource)
                .filter(DiscoveredSource.strategy_id == strategy.id, DiscoveredSource.status == "active")
                .order_by(DiscoveredSource.success_rate.desc())
                .limit(15)
                .all()
            )
            if not discovered:
                log.info(f"[sync_strategy] no discovered sources for strategy {strategy.id} — running discovery")
                from backend.pipeline.discoverer import discover_sources_for_strategy
                try:
                    discover_sources_for_strategy(strategy, db)
                    discovered = (
                        db.query(DiscoveredSource)
                        .filter(DiscoveredSource.strategy_id == strategy.id, DiscoveredSource.status == "active")
                        .limit(15).all()
                    )
                except Exception as e:
                    log.warning(f"[sync_strategy] discovery failed: {e}")

            for ds in discovered:
                run = SyncRun(strategy_id=strategy.id, source=f"discovered:{ds.name}", status="running", started_at=now())
                db.add(run); db.commit()
                try:
                    before = ds.leads_found_total
                    _run_discovered_source(ds, strategy, db)
                    run.leads_found = max(0, ds.leads_found_total - before)
                    run.status = "ok"
                    summary["sources"][f"discovered:{ds.name}"] = {"status": "ok", "saved": run.leads_found}
                except Exception as e:
                    run.status = "error"; run.error = str(e)
                    log.error(f"[sync_strategy] discovered:{ds.name} failed: {e}")
                finally:
                    run.finished_at = now(); db.commit()
        except Exception as e:
            log.error(f"[sync_strategy] discovered-source pass failed: {e}")

        return summary
    finally:
        db.close()


def hourly_sync() -> None:
    from backend.database import SessionLocal
    from backend.enrichment.email import enrich_lead
    from backend.pipeline.scorer import score_lead_smart
    import backend.sources as sources_pkg

    db = SessionLocal()
    try:
        strategies = db.query(Strategy).filter(Strategy.is_active.is_(True)).all()
        log.info(f"Hourly sync: processing {len(strategies)} active strategies")

        for strategy in strategies:
            for source_module in sources_pkg.INTENT_SOURCES:
                run = SyncRun(
                    strategy_id=strategy.id,
                    source=source_module.NAME,
                    status="running",
                    started_at=now(),
                )
                db.add(run)
                db.commit()
                try:
                    raw_leads = source_module.fetch(strategy.raw_icp_params, limit=50)
                    saved = 0
                    for raw in raw_leads:
                        if dedupe_check(db, strategy.user_id, source_module.NAME, raw.get("external_id", "")):
                            continue
                        enriched = enrich_lead(raw)
                        if not has_contact(enriched):
                            continue
                        scored = score_lead_smart(enriched, strategy)
                        if scored["intent_score"] >= strategy.intent_threshold:
                            save_lead(db, strategy, source_module.NAME, enriched, scored)
                            saved += 1
                    run.leads_found = saved
                    run.status = "ok"
                    log.info(f"Source {source_module.NAME} → {saved} new leads for strategy {strategy.id}")
                except Exception as e:
                    run.status = "error"
                    run.error = str(e)
                    log.error(f"Source {source_module.NAME} failed for strategy {strategy.id}: {e}")
                finally:
                    run.finished_at = now()
                    db.commit()

            # Run discovered sources (top 20 by success_rate)
            discovered = (
                db.query(DiscoveredSource)
                .filter(
                    DiscoveredSource.strategy_id == strategy.id,
                    DiscoveredSource.status == "active",
                )
                .order_by(DiscoveredSource.success_rate.desc())
                .limit(20)
                .all()
            )
            for ds in discovered:
                try:
                    _run_discovered_source(ds, strategy, db)
                except Exception as e:
                    ds.last_error = str(e)
                    db.commit()

        if is_first_run_of_week():
            from backend.pipeline.discoverer import discover_sources_for_strategy
            for strategy in strategies:
                try:
                    discover_sources_for_strategy(strategy, db)
                except Exception as e:
                    log.error(f"Weekly discovery failed for strategy {strategy.id}: {e}")

    finally:
        db.close()


def daily_retention_cleanup() -> None:
    from backend.database import SessionLocal
    from backend.config import settings

    db = SessionLocal()
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(days=settings.LEAD_RETENTION_DAYS)
        deleted = db.query(Lead).filter(Lead.created_at < cutoff).delete()
        db.commit()
        log.info(f"Retention cleanup: deleted {deleted} leads older than {settings.LEAD_RETENTION_DAYS} days")
    finally:
        db.close()
