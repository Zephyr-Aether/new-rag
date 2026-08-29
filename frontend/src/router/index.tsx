import { lazy } from 'react'
import { Route, Routes } from 'react-router-dom'
import Layout from '../layout'
import RequireAuth from '../components/RequireAuth'
import AdminGate from '../components/AdminGate'
import Login from '../pages/Login'

// Route-level 分包：每个页面独立 chunk，首屏只加载当前路由
const Dashboard = lazy(() => import('../pages/Dashboard'))
const Runs = lazy(() => import('../pages/Runs'))
const RunDetail = lazy(() => import('../pages/RunDetail'))
const Release = lazy(() => import('../pages/Release'))
const Knowledge = lazy(() => import('../pages/Knowledge'))
const Memory = lazy(() => import('../pages/Memory'))
const Cost = lazy(() => import('../pages/Cost'))
const Tools = lazy(() => import('../pages/Tools'))
const Events = lazy(() => import('../pages/Events'))
const Queue = lazy(() => import('../pages/Queue'))
const Approvals = lazy(() => import('../pages/Approvals'))
const Audit = lazy(() => import('../pages/Audit'))
const Data = lazy(() => import('../pages/Data'))
const Evaluation = lazy(() => import('../pages/Evaluation'))
const Graph = lazy(() => import('../pages/Graph'))
const ConfigCenter = lazy(() => import('../pages/ConfigCenter'))
const ModelHealth = lazy(() => import('../pages/ModelHealth'))
const Policies = lazy(() => import('../pages/Policies'))
const Users = lazy(() => import('../pages/Users'))
const Chat = lazy(() => import('../pages/Chat'))

export default function AppRoutes() {
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
        <Route path="/memory" element={<AdminGate><Memory /></AdminGate>} />
        <Route path="/graph" element={<AdminGate><Graph /></AdminGate>} />
        <Route path="/evaluation" element={<Evaluation />} />
        <Route path="/cost" element={<AdminGate><Cost /></AdminGate>} />
        <Route path="/model" element={<AdminGate><ModelHealth /></AdminGate>} />
        <Route path="/tools" element={<AdminGate><Tools /></AdminGate>} />
        <Route path="/events" element={<AdminGate><Events /></AdminGate>} />
        <Route path="/queue" element={<AdminGate><Queue /></AdminGate>} />
        <Route path="/approvals" element={<AdminGate><Approvals /></AdminGate>} />
        <Route path="/audit" element={<AdminGate><Audit /></AdminGate>} />
        <Route path="/data" element={<AdminGate><Data /></AdminGate>} />
        <Route path="/settings" element={<AdminGate><ConfigCenter /></AdminGate>} />
        <Route path="/policies" element={<AdminGate><Policies /></AdminGate>} />
        <Route path="/users" element={<AdminGate><Users /></AdminGate>} />
      </Route>
    </Routes>
  )
}
