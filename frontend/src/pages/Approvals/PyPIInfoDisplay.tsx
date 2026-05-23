import { useState } from 'react'
import { PyPIPackageInfo } from '../../api/approvals'
import { severityColor, scorecardColor } from './shared'

export function PyPIInfoDisplay({ info, moduleName }: { info: PyPIPackageInfo | null; moduleName: string }) {
  const [vulnsExpanded, setVulnsExpanded] = useState(false)

  if (!info) {
    return (
      <div className="mt-3 rounded border border-hl-med bg-hl-low p-3 text-sm text-subtle">
        Loading package info...
      </div>
    )
  }

  if (info.error) {
    return (
      <div className="mt-3 rounded border border-love/30 bg-love/10 p-3 text-sm text-love">
        Error loading package info: {info.error}
      </div>
    )
  }

  // Stdlib module - safe, no install needed
  if (info.is_stdlib) {
    return (
      <div className="mt-3 rounded border border-foam/30 bg-foam/10 p-3">
        <div className="flex items-center gap-2">
          <span className="rounded bg-foam/10 px-2 py-0.5 text-xs font-medium text-foam">
            Python Stdlib
          </span>
          <span className="text-sm text-foam">
            Built-in module - no installation required
          </span>
        </div>
      </div>
    )
  }

  const hasVulns = info.vulnerability_count > 0
  const borderColor = hasVulns ? 'border-love/40' : 'border-pine/30'
  const bgColor = hasVulns ? 'bg-love/10' : 'bg-pine/10'

  // Third-party package
  return (
    <div className={`mt-3 rounded border ${borderColor} ${bgColor} p-3`}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="rounded bg-pine/10 px-2 py-0.5 text-xs font-medium text-pine">
          PyPI Package
        </span>
        {moduleName !== info.package_name && info.package_name && (
          <span className="text-xs text-subtle">
            installs as <code className="font-mono">{info.package_name}</code>
          </span>
        )}
        {info.is_installed ? (
          <span className="rounded bg-foam/10 px-2 py-0.5 text-xs font-medium text-foam">
            Installed v{info.installed_version}
          </span>
        ) : (
          <span className="rounded bg-gold/10 px-2 py-0.5 text-xs font-medium text-gold">
            Not installed
          </span>
        )}
        {info.latest_version && (
          <span className="text-xs text-subtle">
            Latest: v{info.latest_version}
          </span>
        )}
      </div>

      {info.summary && (
        <p className="mt-2 text-sm text-on-base">{info.summary}</p>
      )}

      <div className="mt-2 flex flex-wrap gap-3 text-xs text-subtle">
        {info.author && <span>Author: {info.author}</span>}
        {info.license && <span>License: {info.license}</span>}
        {info.home_page && (
          <a
            href={info.home_page}
            target="_blank"
            rel="noopener noreferrer"
            className="text-pine hover:underline"
          >
            Project Homepage
          </a>
        )}
      </div>

      {/* Security section */}
      <div className="mt-3 border-t border-hl-med pt-3">
        <div className="flex flex-wrap items-center gap-3">
          {/* Vulnerability badge */}
          {hasVulns ? (
            <button
              onClick={() => setVulnsExpanded(!vulnsExpanded)}
              className="flex items-center gap-1 rounded bg-love/10 px-2 py-0.5 text-xs font-medium text-love hover:bg-love/20"
            >
              {info.vulnerability_count} known {info.vulnerability_count === 1 ? 'vulnerability' : 'vulnerabilities'}
              <span className="ml-1">{vulnsExpanded ? '\u25B2' : '\u25BC'}</span>
            </button>
          ) : (
            <span className="rounded bg-foam/10 px-2 py-0.5 text-xs font-medium text-foam">
              No known vulnerabilities
            </span>
          )}

          {/* OpenSSF Scorecard */}
          {info.scorecard_score !== null && (
            <span className={`text-xs font-medium ${scorecardColor(info.scorecard_score)}`}>
              OpenSSF Score: {info.scorecard_score.toFixed(1)}/10
            </span>
          )}

          {/* Dependency count */}
          {info.dependency_count !== null && (
            <span className="text-xs text-subtle">
              {info.dependency_count} {info.dependency_count === 1 ? 'dependency' : 'dependencies'}
            </span>
          )}

          {/* Source repo link */}
          {info.source_repo && (
            <a
              href={`https://${info.source_repo}`}
              target="_blank"
              rel="noopener noreferrer"
              className="text-xs text-pine hover:underline"
            >
              Source
            </a>
          )}
        </div>

        {/* Expanded vulnerability list */}
        {vulnsExpanded && info.vulnerabilities && info.vulnerabilities.length > 0 && (
          <div className="mt-2 space-y-2">
            {info.vulnerabilities.map((vuln) => (
              <div key={vuln.id} className="rounded border border-love/30 bg-surface p-2 text-xs">
                <div className="flex items-center gap-2">
                  <span className={`rounded px-1.5 py-0.5 text-xs font-medium ${severityColor(vuln.severity)}`}>
                    {vuln.severity || 'UNKNOWN'}
                  </span>
                  {vuln.link ? (
                    <a
                      href={vuln.link}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="font-mono text-pine hover:underline"
                    >
                      {vuln.id}
                    </a>
                  ) : (
                    <span className="font-mono">{vuln.id}</span>
                  )}
                  {vuln.fixed_version && (
                    <span className="text-subtle">
                      Fixed in v{vuln.fixed_version}
                    </span>
                  )}
                </div>
                <p className="mt-1 text-subtle">{vuln.summary}</p>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
