import { useState, KeyboardEvent } from 'react'
import { X } from 'lucide-react'

interface TagInputProps {
  value: string[]
  onChange: (tags: string[]) => void
  placeholder?: string
}

export default function TagInput({ value, onChange, placeholder = 'Add and press Enter' }: TagInputProps) {
  const [input, setInput] = useState('')

  const add = () => {
    const trimmed = input.trim()
    if (trimmed && !value.includes(trimmed)) {
      onChange([...value, trimmed])
    }
    setInput('')
  }

  const remove = (tag: string) => onChange(value.filter((t) => t !== tag))

  const onKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') { e.preventDefault(); add() }
    if (e.key === 'Backspace' && !input && value.length) remove(value[value.length - 1])
  }

  return (
    <div className="flex flex-wrap gap-1.5 border border-gray-200 rounded-lg px-2.5 py-2 focus-within:ring-2 focus-within:ring-primary/30 focus-within:border-primary transition-colors min-h-[42px]">
      {value.map((tag) => (
        <span key={tag} className="flex items-center gap-1 bg-primary/10 text-primary text-xs px-2 py-0.5 rounded-md font-medium">
          {tag}
          <button type="button" onClick={() => remove(tag)} className="hover:text-primary-dark">
            <X className="w-3 h-3" />
          </button>
        </span>
      ))}
      <input
        type="text"
        value={input}
        onChange={(e) => setInput(e.target.value)}
        onKeyDown={onKey}
        onBlur={add}
        placeholder={value.length === 0 ? placeholder : ''}
        className="flex-1 min-w-[120px] outline-none text-sm bg-transparent text-gray-700 placeholder-gray-400"
      />
    </div>
  )
}
