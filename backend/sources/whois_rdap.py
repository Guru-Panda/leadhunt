from __future__ import annotations

import logging

import httpx

log = logging.getLogger(__name__)
NAME = "whois"


def fetch(icp_params: dict, limit: int = 50) -> list[dict]:
    # WHOIS/RDAP is used as enrichment rather than a standalone source.
    # Primary trigger: enrich leads that already have a domain but no contact.
    # For standalone use, query based on tech_keywords in domain space.
    return []


def lookup_domain(domain: str) -> dict | None:
    try:
        domain_part = domain.replace("www.", "")
        tld = domain_part.split(".")[-1]

        rdap_roots = {
            "com": "https://rdap.verisign.com/com/v1/domain/",
            "net": "https://rdap.verisign.com/net/v1/domain/",
            "io": "https://rdap.iana.org/domain/",
            "co": "https://rdap.iana.org/domain/",
        }
        base = rdap_roots.get(tld, "https://rdap.iana.org/domain/")

        r = httpx.get(f"{base}{domain_part}", timeout=10, headers={"User-Agent": "LeadHunt/1.0"})
        if r.status_code != 200:
            return None
        data = r.json()

        for entity in data.get("entities", []):
            roles = entity.get("roles", [])
            if "registrant" not in roles:
                continue
            vcard = entity.get("vcardArray", [[], []])[1]
            result = {}
            for field in vcard:
                if field[0] == "fn":
                    result["name"] = field[3]
                elif field[0] == "email":
                    result["email"] = field[3]
                elif field[0] == "org":
                    result["org"] = field[3]
            return result if result else None
    except Exception as e:
        log.debug(f"RDAP lookup failed for {domain}: {e}")
        return None
