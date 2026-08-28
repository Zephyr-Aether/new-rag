import { useEffect, useRef, useState } from 'react'
import { EditorView, basicSetup } from 'codemirror'
import { EditorState } from '@codemirror/state'
import { json } from '@codemirror/lang-json'
import { python } from '@codemirror/lang-python'
import { oneDark } from '@codemirror/theme-one-dark'
import { Maximize, Minimize } from 'lucide-react'

/** 基于 CodeMirror 的代码编辑器：深色主题 + 语法高亮 + 行号，支持最大高度与全屏。language 可选 json / python。 */
export function CodeEditor({ value, onChange, language = 'json' }: {
  value: string
  onChange: (v: string) => void
  language?: 'json' | 'python'
}) {
  const containerRef = useRef<HTMLDivElement>(null)
  const viewRef = useRef<EditorView | null>(null)
  const [fullscreen, setFullscreen] = useState(false)

  useEffect(() => {
    if (!containerRef.current) return
    const view = new EditorView({
      parent: containerRef.current,
      state: EditorState.create({
        doc: value,
        extensions: [
          basicSetup,
          language === 'python' ? python() : json(),
          oneDark,
          EditorView.updateListener.of((u) => {
            if (u.docChanged) onChange(u.state.doc.toString())
          }),
        ],
      }),
    })
    viewRef.current = view
    return () => {
      view.destroy()
      viewRef.current = null
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // 外部值变化（如异步加载配置）同步进编辑器，避免覆盖用户正在输入的改动
  useEffect(() => {
    const view = viewRef.current
    if (view && view.state.doc.toString() !== value) {
      view.dispatch({ changes: { from: 0, to: view.state.doc.length, insert: value } })
    }
  }, [value])

  // 全屏切换后容器尺寸变化，通知 CodeMirror 重算布局
  useEffect(() => {
    requestAnimationFrame(() => viewRef.current?.requestMeasure())
  }, [fullscreen])

  // Esc 退出全屏
  useEffect(() => {
    if (!fullscreen) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setFullscreen(false)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [fullscreen])

  return (
    <div className={`code-editor${fullscreen ? ' is-fullscreen' : ''}`}>
      <div className="code-editor-toolbar">
        <span className="small muted">{language === 'python' ? 'Python' : 'JSON'}</span>
        <button
          type="button"
          onClick={() => setFullscreen((v) => !v)}
          title={fullscreen ? '退出全屏 (Esc)' : '全屏编辑'}
        >
          {fullscreen ? <Minimize size={14} /> : <Maximize size={14} />}
        </button>
      </div>
      <div ref={containerRef} className="code-editor-body" />
    </div>
  )
}
