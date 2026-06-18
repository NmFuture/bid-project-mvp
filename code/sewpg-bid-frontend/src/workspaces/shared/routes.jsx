import { Route } from 'react-router-dom'
import SharedPerformanceLibrary from './pages/SharedPerformanceLibrary'

export function renderSharedRoutes({ user, showToast }) {
  return (
    <>
      <Route
        path="/workspace/shared/materials/performance"
        element={<SharedPerformanceLibrary showToast={showToast} currentUser={user} />}
      />
    </>
  )
}
