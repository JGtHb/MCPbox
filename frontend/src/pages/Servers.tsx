import { Header } from '../components/Layout'
import { ServerList } from '../components/ServerList'

export function Servers() {
  return (
    <div className="bg-base min-h-full">
      <Header title="Servers" />
      <div className="p-4 sm:p-6">
        <ServerList />
      </div>
    </div>
  )
}
