import { Navigate, Route } from 'react-router-dom'
import WorkspaceAccess from '../shared/WorkspaceAccess'
import TechnicalTenderReview from './pages/TechnicalTenderReview'
import TechnicalProjectList from './pages/TechnicalProjectList'
import TechnicalProjectEntryRedirect from './pages/TechnicalProjectEntryRedirect'
import TechnicalParseResult from './pages/TechnicalParseResult'
import TechnicalOutlineReview from './pages/TechnicalOutlineReview'
import TechnicalGapRecognition from './pages/TechnicalGapRecognition'
import TechnicalCoCreationEditor from './pages/TechnicalCoCreationEditor'
import TechnicalMaterialDB from './pages/TechnicalMaterialDB'
import TechnicalMaterialWiki from './pages/TechnicalMaterialWiki'
import TechnicalCertificateLedger from './pages/TechnicalCertificateLedger'
import TechnicalAuditLog from './pages/TechnicalAuditLog'

const WORKSPACE = 'tech'

const withAccess = (user, element) => (
  <WorkspaceAccess user={user} workspace={WORKSPACE}>
    {element}
  </WorkspaceAccess>
)

export function renderTechnicalRoutes({ user, showToast }) {
  return (
    <>
      <Route
        path="/parse/technical"
        element={withAccess(user, <TechnicalTenderReview showToast={showToast} />)}
      />
      <Route
        path="/workspace/tech"
        element={withAccess(user, <Navigate to="/workspace/tech/projects" replace />)}
      />
      <Route
        path="/workspace/tech/projects"
        element={withAccess(user, <TechnicalProjectList showToast={showToast} />)}
      />
      <Route
        path="/workspace/tech/projects/:id"
        element={withAccess(user, <TechnicalProjectEntryRedirect />)}
      />
      <Route
        path="/workspace/tech/projects/:id/template-directory"
        element={withAccess(user, <TechnicalParseResult showToast={showToast} />)}
      />
      <Route
        path="/workspace/tech/projects/:id/outline"
        element={withAccess(user, <TechnicalOutlineReview showToast={showToast} />)}
      />
      <Route
        path="/workspace/tech/projects/:id/gaps"
        element={withAccess(user, <TechnicalGapRecognition showToast={showToast} />)}
      />
      <Route
        path="/workspace/tech/projects/:id/editor"
        element={withAccess(user, <TechnicalCoCreationEditor showToast={showToast} />)}
      />
      <Route
        path="/workspace/tech/materials/raw"
        element={withAccess(user, <TechnicalMaterialDB showToast={showToast} />)}
      />
      <Route
        path="/workspace/tech/materials/wiki"
        element={withAccess(user, <TechnicalMaterialWiki showToast={showToast} />)}
      />
      <Route
        path="/workspace/tech/materials/certificates"
        element={withAccess(user, <TechnicalCertificateLedger showToast={showToast} />)}
      />
      <Route
        path="/workspace/tech/materials/performance"
        element={<Navigate to="/workspace/shared/materials/performance" replace />}
      />
      <Route
        path="/workspace/tech/logs"
        element={withAccess(user, <TechnicalAuditLog showToast={showToast} />)}
      />
    </>
  )
}
