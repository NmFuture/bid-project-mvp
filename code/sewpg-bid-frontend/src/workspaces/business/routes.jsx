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
import BusinessAuditLog from './pages/BusinessAuditLog'

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
        element={withAccess(user, <BusinessProjectEntryRedirect />)}
      />
      <Route
        path="/workspace/business/projects/:id/template-directory"
        element={withAccess(user, <BusinessParseResult showToast={showToast} />)}
      />
      <Route
        path="/workspace/business/projects/:id/outline"
        element={withAccess(user, <BusinessOutlineReview showToast={showToast} />)}
      />
      <Route
        path="/workspace/business/projects/:id/gaps"
        element={withAccess(user, <BusinessGapRecognition showToast={showToast} />)}
      />
      <Route
        path="/workspace/business/projects/:id/editor"
        element={withAccess(user, <BusinessCoCreationEditor showToast={showToast} />)}
      />
      <Route
        path="/workspace/business/materials/raw"
        element={withAccess(user, <BusinessMaterialDB showToast={showToast} />)}
      />
      <Route
        path="/workspace/business/materials/wiki"
        element={withAccess(user, <BusinessMaterialWiki showToast={showToast} />)}
      />
      <Route
        path="/workspace/business/logs"
        element={withAccess(user, <BusinessAuditLog showToast={showToast} />)}
      />
    </>
  )
}
