import MaterialDBPage from '../../shared/components/MaterialDBPage'
import businessMaterialDbConfig from '../materialDbConfig'

// 薄封装：商务标素材库 = 共享 MaterialDBPage + 商务轨配置（materialDbConfig.js）。
// 路由与对外 props 不变，行为口径与合并前一致。
export default function BusinessMaterialDB({ showToast = () => {} }) {
  return <MaterialDBPage config={businessMaterialDbConfig} showToast={showToast} />
}
