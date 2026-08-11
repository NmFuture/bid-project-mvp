import { Outlet, useLocation, useParams } from 'react-router-dom'
import BusinessProjectStageProgress from './BusinessProjectStageProgress'

export default function BusinessProjectStageLayout({ showToast }) {
  const { id } = useParams()
  const location = useLocation()

  return (
    <div className="flex min-h-0 w-full flex-col gap-4 sm:gap-6">
      <BusinessProjectStageProgress
        key={id}
        projectId={id}
        refreshKey={location.pathname}
        showToast={showToast}
      />
      <Outlet />
    </div>
  )
}
