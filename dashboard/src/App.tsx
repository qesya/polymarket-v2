import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import Sidebar from './components/layout/Sidebar'
import Header from './components/layout/Header'
import Overview from './pages/Overview'
import Positions from './pages/Positions'
import Trades from './pages/Trades'
import Markets from './pages/Markets'
import Models from './pages/Models'
import Risk from './pages/Risk'
import { useWebSocket } from './ws/useWebSocket'

export default function App() {
  useWebSocket() // initialise singleton WS connection

  return (
    <BrowserRouter>
      <div className="flex h-screen overflow-hidden bg-surface">
        <Sidebar />
        <div className="flex flex-col flex-1 min-w-0">
          <Header />
          <main className="flex-1 overflow-y-auto p-6">
            <Routes>
              <Route path="/" element={<Navigate to="/overview" replace />} />
              <Route path="/overview"  element={<Overview />} />
              <Route path="/positions" element={<Positions />} />
              <Route path="/trades"    element={<Trades />} />
              <Route path="/markets"   element={<Markets />} />
              <Route path="/models"    element={<Models />} />
              <Route path="/risk"      element={<Risk />} />
            </Routes>
          </main>
        </div>
      </div>
    </BrowserRouter>
  )
}
