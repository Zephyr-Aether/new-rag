import { lazy } from 'react'
import { Routes, Route } from 'react-router-dom'
import Layout from './layout/Layout'
import RequireAuth from './components/RequireAuth'
import Login from './pages/Login'

// Route-level 分包：每个页面独立 chunk，首屏只加载当前路由（Phase 4）
const Dashboard = lazy(() => import('./pages/Dashboard'))
const Runs = lazy(() => import('./pages/Runs'))
const RunDetail = lazy(() => import('./pages/RunDetail'))
const Release = lazy(() => import('./pages/Release'))
const Knowledge = lazy(() => import('./pages/Knowledge'))
const Memory = lazy(() => import('./pages/Memory'))
const Cost = lazy(() => import('./pages/Cost'))
const Tools = lazy(() => import('./pages/Tools'))
const Events = lazy(() => import('./pages/Events'))
const Queue = lazy(() => import('./pages/Queue'))
const Approvals = lazy(() => import('./pages/Approvals'))
const Audit = lazy(() => import('./pages/Audit'))
const Data = lazy(() => import('./pages/Data'))
const Evaluation = lazy(() => import('./pages/Evaluation'))
const Graph = lazy(() => import('./pages/Graph'))
const ConfigCenter = lazy(() => import('./pages/ConfigCenter'))
const ModelHealth = lazy(() => import('./pages/ModelHealth'))
const Policies = lazy(() => import('./pages/Policies'))
const Users = lazy(() => import('./pages/Users'))
const Chat = lazy(() => import('./pages/Chat'))

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route element={<RequireAuth><Layout /></RequireAuth>}>
        <Route path="/" element={<Dashboard />} />
        <Route path="/runs" element={<Runs />} />
        <Route path="/runs/:id" element={<RunDetail />} />
        <Route path="/chat" element={<Chat />} />
        <Route path="/release" element={<Release />} />
        <Route path="/knowledge" element={<Knowledge />} />
        <Route path="/memory" element={<Memory />} />
        <Route path="/graph" element={<Graph />} />
        <Route path="/evaluation" element={<Evaluation />} />
        <Route path="/cost" element={<Cost />} />
        <Route path="/model" element={<ModelHealth />} />
        <Route path="/tools" element={<Tools />} />
        <Route path="/events" element={<Events />} />
        <Route path="/queue" element={<Queue />} />
        <Route path="/approvals" element={<Approvals />} />
        <Route path="/audit" element={<Audit />} />
        <Route path="/data" element={<Data />} />
        <Route path="/settings" element={<ConfigCenter />} />
        <Route path="/policies" element={<Policies />} />
        <Route path="/users" element={<Users />} />
      </Route>
    </Routes>
  )
}
