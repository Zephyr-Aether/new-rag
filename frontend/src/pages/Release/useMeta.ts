import { useEffect, useState } from 'react'
import { api, Meta } from '@/services'

/** 拉取当前 Agent 元信息（agent_id / agent_version）。 */
export function useMeta() {
  const [meta, setMeta] = useState<Meta | null>(null)
  const [err, setErr] = useState('')
  useEffect(() => {
    api.meta().then(setMeta).catch((e: Error) => setErr(e.message))
  }, [])
  return { meta, err }
}
