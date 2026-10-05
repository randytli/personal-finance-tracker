// Jest's exit status alone does not reject skipped/todo tests.
const fs = require('node:fs')
const result = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'))
const skipped = result.numPendingTests + result.numTodoTests
const summary = `frontend: executed=${result.numPassedTests + result.numFailedTests}, failures=${result.numFailedTests}, skipped=${skipped}, suites=${result.numTotalTestSuites}`
console.log(summary)
if (process.env.GITHUB_STEP_SUMMARY) {
  fs.appendFileSync(process.env.GITHUB_STEP_SUMMARY, `${summary}\n`)
}
if (!result.success || result.numTotalTests === 0 || skipped !== 0 || result.numRuntimeErrorTestSuites !== 0) {
  process.exitCode = 1
}
