import { Component } from 'react'
import type { ReactNode } from 'react'
import { PageError } from '../components/Page'
import { isRecoverableChunkError, tryRecoverChunkError } from '../util'

export default class RouteErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null }

  static getDerivedStateFromError(error: Error) {
    return { error }
  }

  componentDidCatch(error: Error) {
    tryRecoverChunkError(error)
  }

  render() {
    if (this.state.error) {
      const message = isRecoverableChunkError(this.state.error)
        ? '页面资源加载失败，可能是版本更新或网络波动。'
        : this.state.error.message || '页面渲染失败，请重试。'

      return (
        <PageError
          message={message}
          retry={() => window.location.reload()}
        />
      )
    }

    return this.props.children
  }
}
