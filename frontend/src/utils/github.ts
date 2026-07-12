/**
 * GitHub-integration URL helpers shared across surfaces (Settings' connection
 * panel and the export modal's repo picker) so the org-vs-personal branching
 * lives in exactly one place.
 */

import type { InstallationOption } from "../types/github"

/** GitHub's own installation-settings page — org vs. personal account. */
export function installationManageUrl(install: InstallationOption): string {
  return install.account_type === "Organization"
    ? `https://github.com/organizations/${install.account_login}/settings/installations/${install.installation_id}`
    : `https://github.com/settings/installations/${install.installation_id}`
}
