import { Navigate, Route } from 'react-router-dom'
import WorkspaceAccess from '../shared/WorkspaceAccess'
import ProjectPathRedirect from '../shared/ProjectPathRedirect'
import TechnicalTenderReview from './pages/TechnicalTenderReview'
import TechnicalProjectList from './pages/TechnicalProjectList'
import TechnicalProjectEntryRedirect from './pages/TechnicalProjectEntryRedirect'
import TechnicalParseResult from './pages/TechnicalParseResult'
import TechnicalOutlineReview from './pages/TechnicalOutlineReview'
import TechnicalGapRecognition from './pages/TechnicalGapRecognition'
import TechnicalGenerateProgress from './pages/TechnicalGenerateProgress'
import TechnicalCoverageHeatmap from './pages/TechnicalCoverageHeatmap'
import TechnicalCoCreationEditor from './pages/TechnicalCoCreationEditor'
import TechnicalFinalExport from './pages/TechnicalFinalExport'
import TechnicalMaterialDB from './pages/TechnicalMaterialDB'
import TechnicalMaterialWiki from './pages/TechnicalMaterialWiki'
import TechnicalAuditLog from './pages/TechnicalAuditLog'
import './technical.css'

const WORKSPACE = 'tech'

const withAccess = (user, element) => (
  <WorkspaceAccess user={user} workspace={WORKSPACE}>
    <div className="technical-workspace">
      {element}
    </div>
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
        path="/workspace/tech/flow"
        element={withAccess(user, <Navigate to="/workspace/tech/projects" replace />)}
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
        path="/workspace/tech/projects/:id/parse"
        element={withAccess(user, <ProjectPathRedirect path="/template-directory" />)}
      />
      <Route
        path="/workspace/tech/projects/:id/directory"
        element={withAccess(user, <ProjectPathRedirect path="/template-directory" />)}
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
        path="/workspace/tech/projects/:id/gaps-fill"
        element={withAccess(user, <ProjectPathRedirect path="/gaps" />)}
      />
      <Route
        path="/workspace/tech/projects/:id/gaps/review"
        element={withAccess(user, <ProjectPathRedirect path="/gaps" />)}
      />
      <Route
        path="/workspace/tech/projects/:id/generate"
        element={withAccess(user, <TechnicalGenerateProgress showToast={showToast} />)}
      />
      <Route
        path="/workspace/tech/projects/:id/coverage"
        element={withAccess(user, <TechnicalCoverageHeatmap showToast={showToast} />)}
      />
      <Route
        path="/workspace/tech/projects/:id/editor"
        element={withAccess(user, <TechnicalCoCreationEditor showToast={showToast} />)}
      />
      <Route
        path="/workspace/tech/projects/:id/export"
        element={withAccess(user, <TechnicalFinalExport showToast={showToast} />)}
      />
      <Route
        path="/workspace/tech/materials/structured"
        element={withAccess(user, <TechnicalMaterialDB showToast={showToast} />)}
      />
      <Route
        path="/workspace/tech/materials/wiki"
        element={withAccess(user, <TechnicalMaterialWiki showToast={showToast} />)}
      />
      <Route
        path="/workspace/tech/logs"
        element={withAccess(user, <TechnicalAuditLog showToast={showToast} />)}
      />
    </>
  )
}
