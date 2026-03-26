import { useState, useEffect, useRef } from 'react'
import { Document, Page, pdfjs } from 'react-pdf'
import 'react-pdf/dist/Page/TextLayer.css'
import 'react-pdf/dist/Page/AnnotationLayer.css'

pdfjs.GlobalWorkerOptions.workerSrc = `https://unpkg.com/pdfjs-dist@${pdfjs.version}/build/pdf.worker.min.mjs`

type Props = {
  documentId: string
  chunkText: string
}

export default function PDFViewer({ documentId, chunkText }: Props) {
  const [numPages, setNumPages] = useState<number>(0)
  const [containerWidth, setContainerWidth] = useState<number>(600)
  const containerRef = useRef<HTMLDivElement>(null)
  const highlightRef = useRef<HTMLDivElement>(null)
  const hasScrolled = useRef(false)

  const url = `http://localhost:8000/documents/${documentId}/file`

  // Track container width for responsive pages
  useEffect(() => {
    if (!containerRef.current) return
    const ro = new ResizeObserver(([entry]) => {
      setContainerWidth(entry.contentRect.width)
    })
    ro.observe(containerRef.current)
    return () => ro.disconnect()
  }, [])

  // Scroll to first highlight after render
  useEffect(() => {
    if (highlightRef.current && !hasScrolled.current) {
      hasScrolled.current = true
      highlightRef.current.scrollIntoView({ behavior: 'smooth', block: 'center' })
    }
  })

  // Reset scroll flag when chunk changes
  useEffect(() => {
    hasScrolled.current = false
  }, [chunkText])

  // Normalize whitespace for matching
  const normalize = (s: string) => s.replace(/\s+/g, ' ').trim()
  const normalizedChunk = normalize(chunkText)

  function customTextRenderer({ str }: { str: string }) {
    const normalizedStr = normalize(str)
    if (normalizedStr.length < 4) return str
    if (normalizedChunk.includes(normalizedStr)) {
      return `<mark data-chunk-highlight style="background:oklch(0.97 0.05 90);border-radius:2px;padding:0 1px">${str}</mark>`
    }
    return str
  }

  function onDocumentLoadSuccess({ numPages }: { numPages: number }) {
    setNumPages(numPages)
  }

  return (
    <div ref={containerRef} className="w-full">
      <Document
        file={url}
        onLoadSuccess={onDocumentLoadSuccess}
        loading={<p className="text-xs text-muted-foreground py-4">Loading PDF…</p>}
        error={<p className="text-xs text-destructive py-4">Could not load PDF.</p>}
      >
        {Array.from({ length: numPages }, (_, i) => (
          <div key={i} className="mb-4">
            <Page
              pageNumber={i + 1}
              width={containerWidth}
              customTextRenderer={customTextRenderer}
              renderAnnotationLayer={false}
              onRenderTextLayerSuccess={() => {
                // Attach ref to first highlight element found
                if (!hasScrolled.current) {
                  const el = document.querySelector('[data-chunk-highlight]')
                  if (el) {
                    hasScrolled.current = true
                    el.scrollIntoView({ behavior: 'smooth', block: 'center' })
                  }
                }
              }}
            />
          </div>
        ))}
      </Document>
    </div>
  )
}
