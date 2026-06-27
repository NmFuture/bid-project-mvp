export const BUSINESS_PARSE_RESULT_DISPLAY = {
  RESULT: 'result',
  NO_SOURCE: 'no-source',
  PENDING: 'pending',
}

export const businessParseResultDisplayState = ({
  isParseCompleted = false,
  sourceFiles = [],
} = {}) => {
  if (isParseCompleted) return BUSINESS_PARSE_RESULT_DISPLAY.RESULT
  if (!Array.isArray(sourceFiles) || !sourceFiles.length) return BUSINESS_PARSE_RESULT_DISPLAY.NO_SOURCE
  return BUSINESS_PARSE_RESULT_DISPLAY.PENDING
}
