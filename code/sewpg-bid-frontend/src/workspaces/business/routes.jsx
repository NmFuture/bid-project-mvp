import { Navigate, Route } from 'react-router-dom'
import WorkspaceAccess from '../shared/WorkspaceAccess'
import BusinessTenderReview from './pages/BusinessTenderReview'
import BusinessProjectList from './pages/BusinessProjectList'
import BusinessProjectEntryRedirect from './pages/BusinessProjectEntryRedirect'
import BusinessParseResult from './pages/BusinessParseResult'
import BusinessOutlineReview from './pages/BusinessOutlineReview'
import BusinessGapRecognition from './pages/BusinessGapRecognition'
import BusinessCoCreationEditor from './pages/BusinessCoCreationEditor'
import BusinessMaterialDB from './pages/BusinessMaterialDB'
import BusinessMaterialWiki from './pages/BusinessMaterialWiki'
import AuditLogCenter from '../shared/pages/AuditLogCenter'
import BusinessProjectStageLayout from './components/BusinessProjectStageLayout'

const WORKSPACE = 'business'

const withAccess = (user, element) => (
  <WorkspaceAccess user={user} workspace={WORKSPACE}>
    {element}
  </WorkspaceAccess>
)

export function renderBusinessRoutes({ user, showToast }) {
  return (
    <>
      <Route
        path="/parse/business"
        element={withAccess(user, <BusinessTenderReview showToast={showToast} />)}
      />
      <Route
        path="/workspace/business"
        element={withAccess(user, <Navigate to="/workspace/business/projects" replace />)}
      />
      <Route
        path="/workspace/business/projects"
        element={withAccess(user, <BusinessProjectList showToast={showToast} />)}
      />
      <Route
        path="/workspace/business/projects/:id"
        element={withAccess(user, <BusinessProjectStageLayout showToast={showToast} />)}
      >
        <Route index element={<BusinessProjectEntryRedirect />} />
        <Route path="template-directory" element={<BusinessParseResult showToast={showToast} />} />
        <Route path="outline" element={<BusinessOutlineReview showToast={showToast} />} />
        <Route path="gaps" element={<BusinessGapRecognition showToast={showToast} />} />
        <Route path="editor" element={<BusinessCoCreationEditor showToast={showToast} />} />
      </Route>
      <Route
        path="/workspace/business/materials/raw"
        element={withAccess(user, <BusinessMaterialDB showToast={showToast} />)}
      />
      <Route
        path="/workspace/business/materials/wiki"
        element={withAccess(user, <BusinessMaterialWiki showToast={showToast} />)}
      />
      <Route
        path="/workspace/business/materials/performance"
        element={<Navigate to="/workspace/shared/materials/performance" replace />}
      />
      <Route
        path="/workspace/business/logs"
        element={withAccess(user, <AuditLogCenter showToast={showToast} />)}
      />
    </>
  )
}
