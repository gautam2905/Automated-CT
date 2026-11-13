import { useEffect } from 'react'
import ConsolePanel from './panels/ConsolePanel'
import ProcedurePanel from './panels/ProcedurePanel'
import TopBar from './panels/TopBar'
import RoomScene from './scene/RoomScene'
import { useSession } from './store/session'

export default function App() {
  const loadCatalog = useSession((s) => s.loadCatalog)
  useEffect(() => {
    void loadCatalog()
  }, [loadCatalog])

  return (
    <div className="app">
      <TopBar />
      <main className="app__body">
        <ProcedurePanel />
        <RoomScene />
        <ConsolePanel />
      </main>
    </div>
  )
}
