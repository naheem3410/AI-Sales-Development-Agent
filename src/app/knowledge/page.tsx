'use client'
import { useState, useEffect, useCallback, useRef } from 'react'
import Link from 'next/link'
import { useApiClient } from '@/hooks/useApiClient'
import { Empty, Spinner } from '@/components/ui'
import { formatApiError, formatDateTime } from '@/lib/utils'
import type { RagDocumentListItem, RagSourceType } from '@/types/api'
import { toast } from 'sonner'
import {
  ArrowLeft,
  BookOpen,
  Upload,
  FileText,
  Trash2,
  Loader2,
} from 'lucide-react'

const SOURCE_OPTIONS: { value: RagSourceType; label: string }[] = [
  { value: 'faq', label: 'FAQ' },
  { value: 'company_info', label: 'Company info' },
  { value: 'email_template', label: 'Email template' },
  { value: 'other', label: 'Other' },
]

export default function KnowledgePage() {
  const { getClient } = useApiClient()
  const fileInputRef = useRef<HTMLInputElement>(null)

  const [docs, setDocs] = useState<RagDocumentListItem[]>([])
  const [loading, setLoading] = useState(true)
  const [uploadingFile, setUploadingFile] = useState(false)
  const [uploadingText, setUploadingText] = useState(false)
  const [deletingId, setDeletingId] = useState<string | null>(null)

  const [fileMeta, setFileMeta] = useState({
    source_type: 'faq' as RagSourceType,
    title: '',
  })
  const [textForm, setTextForm] = useState({
    title: '',
    source_type: 'faq' as RagSourceType,
    content: '',
  })

  const load = useCallback(async () => {
    try {
      const client = await getClient()
      const res = await client.listRagDocuments()
      setDocs(res.documents)
    } catch {
      toast.error('Failed to load knowledge documents')
    } finally {
      setLoading(false)
    }
  }, [getClient])

  useEffect(() => {
    load()
  }, [load])

  const onPickFile = () => fileInputRef.current?.click()

  const onFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (!file) return

    setUploadingFile(true)
    try {
      const client = await getClient()
      const form = new FormData()
      form.append('file', file)
      form.append('source_type', fileMeta.source_type)
      if (fileMeta.title.trim()) form.append('title', fileMeta.title.trim())
      await client.uploadRagDocumentFile(form)
      toast.success(`“${file.name}” ingested`)
      setFileMeta((p) => ({ ...p, title: '' }))
      await load()
    } catch (err) {
      toast.error(formatApiError(err))
    } finally {
      setUploadingFile(false)
    }
  }

  const submitText = async () => {
    if (textForm.title.trim().length < 1) {
      toast.error('Enter a title')
      return
    }
    if (textForm.content.trim().length < 10) {
      toast.error('Content must be at least 10 characters')
      return
    }
    setUploadingText(true)
    try {
      const client = await getClient()
      await client.uploadRagDocument({
        title: textForm.title.trim(),
        source_type: textForm.source_type,
        content: textForm.content.trim(),
      })
      toast.success('Document added to your knowledge base')
      setTextForm({ title: '', source_type: 'faq', content: '' })
      await load()
    } catch (err) {
      toast.error(formatApiError(err))
    } finally {
      setUploadingText(false)
    }
  }

  const remove = async (id: string) => {
    setDeletingId(id)
    try {
      const client = await getClient()
      await client.deleteRagDocument(id)
      toast.success('Document removed')
      await load()
    } catch (err) {
      toast.error(formatApiError(err))
    } finally {
      setDeletingId(null)
    }
  }

  return (
    <div className="p-8 max-w-4xl mx-auto animate-fade-in">
      <Link
        href="/dashboard"
        className="inline-flex items-center gap-1.5 text-sm text-ink-muted hover:text-ink mb-5 transition-colors"
      >
        <ArrowLeft size={14} /> Back to Dashboard
      </Link>

      <div className="flex items-start gap-4 mb-8">
        <div className="w-12 h-12 rounded-2xl bg-brand-100 flex items-center justify-center flex-shrink-0">
          <BookOpen size={22} className="text-brand-700" />
        </div>
        <div>
          <h1 className="text-2xl font-semibold text-ink tracking-tight">Knowledge base</h1>
          <p className="text-sm text-ink-muted mt-1 max-w-2xl">
            Upload FAQs, positioning, and proven templates. When leads reply, the AI uses this context to draft accurate responses — alongside your campaign brief.
          </p>
        </div>
      </div>

      <div className="grid gap-6 lg:grid-cols-2 mb-10">
        {/* File upload */}
        <div className="card p-6">
          <div className="flex items-center gap-2 mb-4">
            <div className="w-8 h-8 rounded-xl bg-surface-100 flex items-center justify-center">
              <Upload size={16} className="text-brand-600" />
            </div>
            <div>
              <h2 className="text-sm font-semibold text-ink">Upload a file</h2>
              <p className="text-xs text-ink-subtle">PDF, Word (.docx), plain text, or Markdown</p>
            </div>
          </div>

          <div className="space-y-4">
            <div>
              <label className="label">Category</label>
              <select
                className="input"
                value={fileMeta.source_type}
                onChange={(e) =>
                  setFileMeta((p) => ({ ...p, source_type: e.target.value as RagSourceType }))
                }
              >
                {SOURCE_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="label">Title override (optional)</label>
              <input
                className="input"
                placeholder="Defaults to filename"
                value={fileMeta.title}
                onChange={(e) => setFileMeta((p) => ({ ...p, title: e.target.value }))}
              />
            </div>

            <input
              ref={fileInputRef}
              type="file"
              accept=".pdf,.docx,.txt,.md,.markdown"
              className="hidden"
              onChange={onFileChange}
            />

            <button
              type="button"
              className="btn-secondary w-full justify-center py-8 border-2 border-dashed border-surface-300 hover:border-brand-400 hover:bg-brand-50/50 transition-colors"
              onClick={onPickFile}
              disabled={uploadingFile}
            >
              {uploadingFile ? (
                <Loader2 size={20} className="animate-spin text-brand-600" />
              ) : (
                <>
                  <Upload size={18} />
                  Choose file
                </>
              )}
            </button>
          </div>
        </div>

        {/* Paste text */}
        <div className="card p-6">
          <div className="flex items-center gap-2 mb-4">
            <div className="w-8 h-8 rounded-xl bg-surface-100 flex items-center justify-center">
              <FileText size={16} className="text-brand-600" />
            </div>
            <div>
              <h2 className="text-sm font-semibold text-ink">Add from text</h2>
              <p className="text-xs text-ink-subtle">Paste content directly (JSON-safe)</p>
            </div>
          </div>

          <div className="space-y-3">
            <div>
              <label className="label">Title</label>
              <input
                className="input"
                value={textForm.title}
                onChange={(e) => setTextForm((p) => ({ ...p, title: e.target.value }))}
                placeholder="e.g. Pricing FAQ"
              />
            </div>
            <div>
              <label className="label">Category</label>
              <select
                className="input"
                value={textForm.source_type}
                onChange={(e) =>
                  setTextForm((p) => ({ ...p, source_type: e.target.value as RagSourceType }))
                }
              >
                {SOURCE_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="label">Content</label>
              <textarea
                className="input min-h-[180px] resize-y font-mono text-xs"
                value={textForm.content}
                onChange={(e) => setTextForm((p) => ({ ...p, content: e.target.value }))}
                placeholder="Paste your text here…"
              />
            </div>
            <button
              type="button"
              className="btn-primary w-full"
              onClick={submitText}
              disabled={uploadingText}
            >
              {uploadingText ? <Spinner size={16} /> : null}
              Add to knowledge base
            </button>
          </div>
        </div>
      </div>

      {/* Library */}
      <div className="card overflow-hidden">
        <div className="px-6 py-4 border-b border-surface-200 bg-surface-50">
          <h2 className="text-sm font-semibold text-ink">Your documents</h2>
          <p className="text-xs text-ink-subtle mt-0.5">{docs.length} total</p>
        </div>

        {loading ? (
          <div className="p-12 flex justify-center">
            <Spinner size={28} />
          </div>
        ) : docs.length === 0 ? (
          <Empty
            icon={<BookOpen size={22} />}
            title="No documents yet"
            description="Upload a file or paste text to build your knowledge base."
          />
        ) : (
          <div className="divide-y divide-surface-100">
            {docs.map((d) => (
              <div
                key={d.id}
                className="flex items-start gap-4 px-6 py-4 hover:bg-surface-50/80 transition-colors"
              >
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-ink truncate">{d.title}</p>
                  <p className="text-xs text-ink-subtle mt-0.5">
                    {d.source_type.replace(/_/g, ' ')} · {d.chunk_count} chunks
                    {d.embedded_at && ` · Embedded ${formatDateTime(d.embedded_at)}`}
                  </p>
                </div>
                <button
                  type="button"
                  className="btn-ghost btn-sm text-red-600 hover:bg-red-50 hover:text-red-700"
                  onClick={() => remove(d.id)}
                  disabled={deletingId === d.id}
                  title="Remove document"
                >
                  {deletingId === d.id ? (
                    <Spinner size={14} />
                  ) : (
                    <Trash2 size={14} />
                  )}
                </button>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
