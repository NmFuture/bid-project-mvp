import TenderReview from './TenderReview'

const BUSINESS_REVIEW_PAGE_CONFIG = {
  bidType: '商务标',
}

export default function BusinessTenderReview({ showToast }) {
  return <TenderReview showToast={showToast} config={BUSINESS_REVIEW_PAGE_CONFIG} />
}
