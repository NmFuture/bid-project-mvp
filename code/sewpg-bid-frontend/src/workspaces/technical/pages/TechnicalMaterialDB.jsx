import MaterialDBPage from '../../shared/components/MaterialDBPage'
import technicalMaterialDbConfig from '../materialDbConfig'

// 薄封装：技术标素材库 = 共享 MaterialDBPage + 技术轨配置（materialDbConfig.js）。
// 路由与对外 props 不变，行为口径与合并前一致。
export default function TechnicalMaterialDB({ showToast = () => {} }) {
  return <MaterialDBPage config={technicalMaterialDbConfig} showToast={showToast} />
}
