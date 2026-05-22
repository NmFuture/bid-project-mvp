import { Navigate, Route } from 'react-router-dom'
import WorkspaceAccess from '../shared/WorkspaceAccess'
import ProjectPathRedirect from '../shared/ProjectPathRedirect'
import BusinessTenderReviewPage from './pages/BusinessTenderReviewPage'
import BusinessProjectList from './pages/BusinessProjectList'
import BusinessProjectEntryRedirect from './pages/BusinessProjectEntryRedirect'
import BusinessParseResult from './pages/BusinessParseResult'
import BusinessOutlineReview from './pages/BusinessOutlineReview'
import BusinessGapRecognitionPage from './pages/BusinessGapRecognitionPage'
import BusinessGenerateProgress from './pages/BusinessGenerateProgress'
import BusinessCoverageHeatmap from './pages/BusinessCoverageHeatmap'
import BusinessCoCreationEditor from './pages/BusinessCoCreationEditor'
import BusinessFinalExport from './pages/BusinessFinalExport'
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
        element={withAccess(user, <BusinessTenderReviewPage showToast={showToast} />)}
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
        path="/workspace/business/flow"
        element={withAccess(user, <Navigate to="/workspace/business/projects" replace />)}
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
        path="/workspace/business/projects/:id/parse"
        element={withAccess(user, <ProjectPathRedirect path="/template-directory" />)}
      />
      <Route
        path="/workspace/business/projects/:id/directory"
        element={withAccess(user, <ProjectPathRedirect path="/template-directory" />)}
      />
      <Route
        path="/workspace/business/projects/:id/outline"
        element={withAccess(user, <BusinessOutlineReview showToast={showToast} />)}
      />
      <Route
        path="/workspace/business/projects/:id/gaps"
        element={withAccess(user, <BusinessGapRecognitionPage showToast={showToast} />)}
      />
      <Route
        path="/workspace/business/projects/:id/gaps-fill"
        element={withAccess(user, <ProjectPathRedirect path="/gaps" />)}
      />
      <Route
        path="/workspace/business/projects/:id/gaps/review"
        element={withAccess(user, <ProjectPathRedirect path="/gaps" />)}
      />
      <Route
        path="/workspace/business/projects/:id/generate"
        element={withAccess(user, <BusinessGenerateProgress showToast={showToast} />)}
      />
      <Route
        path="/workspace/business/projects/:id/coverage"
        element={withAccess(user, <BusinessCoverageHeatmap showToast={showToast} />)}
      />
      <Route
        path="/workspace/business/projects/:id/editor"
        element={withAccess(user, <BusinessCoCreationEditor showToast={showToast} />)}
      />
      <Route
        path="/workspace/business/projects/:id/export"
        element={withAccess(user, <BusinessFinalExport showToast={showToast} />)}
      />
      <Route
        path="/workspace/business/materials/structured"
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
