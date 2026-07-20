# Issue #30 frontend review manifest

Audit baseline: `d94da8b71a0438b1c9ca247cfb10a835af694b41`

Every baseline file is explicit. `reviewed/no finding` means it was included in the automated evidence and its subsystem pass; generated/remediation files added after the baseline are described in the consolidated report.

| File | Workstream | Status | Evidence |
|---|---|---|---|
| `frontend/.env.example` | Components/runtime | reviewed/no finding | Static review + subsystem gate |
| `frontend/index.html` | Components/runtime | reviewed/no finding | Static review + subsystem gate |
| `frontend/package.json` | Build/deploy | reviewed/no finding | Static review + subsystem gate |
| `frontend/pnpm-lock.yaml` | Components/runtime | reviewed/no finding | Static review + subsystem gate |
| `frontend/pnpm-workspace.yaml` | Components/runtime | reviewed/no finding | Static review + subsystem gate |
| `frontend/public/.gitkeep` | Components/runtime | reviewed/no finding | Static review + subsystem gate |
| `frontend/public/_headers` | Components/runtime | reviewed/no finding | Static review + subsystem gate |
| `frontend/public/apple-touch-icon.png` | Components/runtime | reviewed/no finding | Static review + subsystem gate |
| `frontend/public/brand/squirrel-mark-export.png` | Components/runtime | reviewed/no finding | Static review + subsystem gate |
| `frontend/public/brand/squirrel-mark.png` | Components/runtime | reviewed/no finding | Static review + subsystem gate |
| `frontend/public/favicon.png` | Components/runtime | reviewed/no finding | Static review + subsystem gate |
| `frontend/public/robots.txt` | Components/runtime | reviewed/no finding | Static review + subsystem gate |
| `frontend/src/App.tsx` | Components/runtime | reviewed/no finding | Static review + subsystem gate |
| `frontend/src/__tests__/AuthCallback.branded.test.tsx` | Tests/contracts | reviewed/no finding | Executed test + static review |
| `frontend/src/__tests__/AuthCallback.test.tsx` | Tests/contracts | reviewed/no finding | Executed test + static review |
| `frontend/src/__tests__/Billing.test.tsx` | Tests/contracts | reviewed/no finding | Executed test + static review |
| `frontend/src/__tests__/CreditSystem.test.tsx` | Tests/contracts | reviewed/no finding | Executed test + static review |
| `frontend/src/__tests__/ErrorBoundary.test.tsx` | Tests/contracts | reviewed/no finding | Executed test + static review |
| `frontend/src/__tests__/Landing.test.tsx` | Tests/contracts | reviewed/no finding | Executed test + static review |
| `frontend/src/__tests__/MarkdownRenderer.test.tsx` | Tests/contracts | reviewed/no finding | Executed test + static review |
| `frontend/src/__tests__/WorkspaceFlow.test.tsx` | Tests/contracts | reviewed/no finding | Executed test + static review |
| `frontend/src/__tests__/setup.ts` | Tests/contracts | reviewed/no finding | Executed test + static review |
| `frontend/src/__tests__/sseService.test.ts` | Tests/contracts | reviewed/no finding | Executed test + static review |
| `frontend/src/__tests__/useFocusTrap.test.tsx` | Tests/contracts | reviewed/no finding | Executed test + static review |
| `frontend/src/components/ErrorBoundary.tsx` | Components/runtime | reviewed/no finding | Static review + subsystem gate |
| `frontend/src/components/dashboard/CreateWorkspaceModal.test.tsx` | Tests/contracts | reviewed/no finding | Executed test + static review |
| `frontend/src/components/dashboard/CreateWorkspaceModal.tsx` | Components/runtime | reviewed/no finding | Static review + subsystem gate |
| `frontend/src/components/dashboard/CreditBanner.tsx` | Components/runtime | reviewed/no finding | Static review + subsystem gate |
| `frontend/src/components/dashboard/DeleteWorkspaceModal.test.tsx` | Tests/contracts | reviewed/no finding | Executed test + static review |
| `frontend/src/components/dashboard/DeleteWorkspaceModal.tsx` | Components/runtime | reviewed/no finding | Static review + subsystem gate |
| `frontend/src/components/dashboard/RecentlyDeletedSection.test.tsx` | Tests/contracts | reviewed/no finding | Executed test + static review |
| `frontend/src/components/dashboard/RecentlyDeletedSection.tsx` | Components/runtime | reviewed/no finding | Static review + subsystem gate |
| `frontend/src/components/dashboard/WorkspaceCard.tsx` | Components/runtime | reviewed/no finding | Static review + subsystem gate |
| `frontend/src/components/github/ExportStatusBadge.tsx` | Components/runtime | reviewed/no finding | Static review + subsystem gate |
| `frontend/src/components/settings/DataRetentionPanel.tsx` | Components/runtime | reviewed/no finding | Static review + subsystem gate |
| `frontend/src/components/settings/GitHubConnection.test.tsx` | Tests/contracts | reviewed/no finding | Executed test + static review |
| `frontend/src/components/settings/GitHubConnection.tsx` | Components/runtime | reviewed/no finding | Static review + subsystem gate |
| `frontend/src/components/shared/.gitkeep` | Components/runtime | reviewed/no finding | Static review + subsystem gate |
| `frontend/src/components/shared/ActionAlert.test.tsx` | Tests/contracts | reviewed/no finding | Executed test + static review |
| `frontend/src/components/shared/ActionAlert.tsx` | Components/runtime | reviewed/no finding | Static review + subsystem gate |
| `frontend/src/components/shared/AiDisclaimer.test.tsx` | Tests/contracts | reviewed/no finding | Executed test + static review |
| `frontend/src/components/shared/AiDisclaimer.tsx` | Components/runtime | reviewed/no finding | Static review + subsystem gate |
| `frontend/src/components/shared/BrandLoader.test.tsx` | Tests/contracts | reviewed/no finding | Executed test + static review |
| `frontend/src/components/shared/BrandLoader.tsx` | Components/runtime | reviewed/no finding | Static review + subsystem gate |
| `frontend/src/components/shared/BrandLogo.test.tsx` | Tests/contracts | reviewed/no finding | Executed test + static review |
| `frontend/src/components/shared/BrandLogo.tsx` | Components/runtime | reviewed/no finding | Static review + subsystem gate |
| `frontend/src/components/shared/CreditMeter.tsx` | Components/runtime | reviewed/no finding | Static review + subsystem gate |
| `frontend/src/components/shared/DashboardIcons.tsx` | Components/runtime | reviewed/no finding | Static review + subsystem gate |
| `frontend/src/components/shared/GitHubStatusPill.tsx` | Components/runtime | reviewed/no finding | Static review + subsystem gate |
| `frontend/src/components/shared/PipelineStageTrack.tsx` | Components/runtime | reviewed/no finding | Static review + subsystem gate |
| `frontend/src/components/shared/ProtectedRoute.branded.test.tsx` | Tests/contracts | reviewed/no finding | Executed test + static review |
| `frontend/src/components/shared/ProtectedRoute.tsx` | Components/runtime | reviewed/no finding | Static review + subsystem gate |
| `frontend/src/components/shared/SessionExpiryWatcher.test.tsx` | Tests/contracts | reviewed/no finding | Executed test + static review |
| `frontend/src/components/shared/SessionExpiryWatcher.tsx` | Components/runtime | reviewed/no finding | Static review + subsystem gate |
| `frontend/src/components/shared/SquirrelMark.tsx` | Components/runtime | reviewed/no finding | Static review + subsystem gate |
| `frontend/src/components/shared/icons.tsx` | Components/runtime | reviewed/no finding | Static review + subsystem gate |
| `frontend/src/components/storyboard/ArchitectureReveal.test.tsx` | Tests/contracts | reviewed/no finding | Executed test + static review |
| `frontend/src/components/storyboard/ArchitectureReveal.tsx` | Components/runtime | reviewed/no finding | Static review + subsystem gate |
| `frontend/src/components/storyboard/PresenterMode.test.tsx` | Tests/contracts | reviewed/no finding | Executed test + static review |
| `frontend/src/components/storyboard/PresenterMode.tsx` | Components/runtime | reviewed/no finding | Static review + subsystem gate |
| `frontend/src/components/storyboard/SourceLayer.test.tsx` | Tests/contracts | reviewed/no finding | Executed test + static review |
| `frontend/src/components/storyboard/SourceLayer.tsx` | Components/runtime | reviewed/no finding | Static review + subsystem gate |
| `frontend/src/components/storyboard/StoryboardDeck.test.tsx` | Tests/contracts | reviewed/no finding | Executed test + static review |
| `frontend/src/components/storyboard/StoryboardDeck.tsx` | Components/runtime | reviewed/no finding | Static review + subsystem gate |
| `frontend/src/components/storyboard/StoryboardDownloadMenu.test.tsx` | Tests/contracts | reviewed/no finding | Executed test + static review |
| `frontend/src/components/storyboard/StoryboardDownloadMenu.tsx` | Components/runtime | reviewed/no finding | Static review + subsystem gate |
| `frontend/src/components/storyboard/StoryboardLaunchPage.tsx` | Components/runtime | reviewed/no finding | Static review + subsystem gate |
| `frontend/src/components/storyboard/StoryboardShareModal.test.tsx` | Tests/contracts | reviewed/no finding | Executed test + static review |
| `frontend/src/components/storyboard/StoryboardShareModal.tsx` | Components/runtime | reviewed/no finding | Static review + subsystem gate |
| `frontend/src/components/storyboard/testPayload.ts` | Tests/contracts | reviewed/no finding | Executed test + static review |
| `frontend/src/components/templates/TemplateCard.tsx` | Components/runtime | reviewed/no finding | Static review + subsystem gate |
| `frontend/src/components/templates/TemplatesStrip.tsx` | Components/runtime | reviewed/no finding | Static review + subsystem gate |
| `frontend/src/components/workspace/.gitkeep` | Components/runtime | reviewed/no finding | Static review + subsystem gate |
| `frontend/src/components/workspace/AdvisoryFindingsPanel.test.tsx` | Tests/contracts | reviewed/no finding | Executed test + static review |
| `frontend/src/components/workspace/AdvisoryFindingsPanel.tsx` | Components/runtime | reviewed/no finding | Static review + subsystem gate |
| `frontend/src/components/workspace/BlockedPartialBanner.test.tsx` | Tests/contracts | reviewed/no finding | Executed test + static review |
| `frontend/src/components/workspace/BlockedPartialBanner.tsx` | Components/runtime | reviewed/no finding | Static review + subsystem gate |
| `frontend/src/components/workspace/ConstructionVerifiedBadge.test.tsx` | Tests/contracts | reviewed/no finding | Executed test + static review |
| `frontend/src/components/workspace/ConstructionVerifiedBadge.tsx` | Components/runtime | reviewed/no finding | Static review + subsystem gate |
| `frontend/src/components/workspace/CoveragePanel.test.tsx` | Tests/contracts | reviewed/no finding | Executed test + static review |
| `frontend/src/components/workspace/CoveragePanel.tsx` | Components/runtime | reviewed/no finding | Static review + subsystem gate |
| `frontend/src/components/workspace/CreateStoryboardModal.test.tsx` | Tests/contracts | reviewed/no finding | Executed test + static review |
| `frontend/src/components/workspace/CreateStoryboardModal.tsx` | Components/runtime | reviewed/no finding | Static review + subsystem gate |
| `frontend/src/components/workspace/CreditConfirmModal.tsx` | Components/runtime | reviewed/no finding | Static review + subsystem gate |
| `frontend/src/components/workspace/DemoDayHandoffPanel.test.tsx` | Tests/contracts | reviewed/no finding | Executed test + static review |
| `frontend/src/components/workspace/DemoDayHandoffPanel.tsx` | Components/runtime | reviewed/no finding | Static review + subsystem gate |
| `frontend/src/components/workspace/DiffViewer.test.tsx` | Tests/contracts | reviewed/no finding | Executed test + static review |
| `frontend/src/components/workspace/DiffViewer.tsx` | Components/runtime | reviewed/no finding | Static review + subsystem gate |
| `frontend/src/components/workspace/ExportGitHubModal.test.tsx` | Tests/contracts | reviewed/no finding | Executed test + static review |
| `frontend/src/components/workspace/ExportGitHubModal.tsx` | Components/runtime | reviewed/no finding | Static review + subsystem gate |
| `frontend/src/components/workspace/ExportPDFButton.tsx` | Components/runtime | reviewed/no finding | Static review + subsystem gate |
| `frontend/src/components/workspace/GenerateBar.branded.test.tsx` | Tests/contracts | reviewed/no finding | Executed test + static review |
| `frontend/src/components/workspace/GenerateBar.tsx` | Components/runtime | reviewed/no finding | Static review + subsystem gate |
| `frontend/src/components/workspace/HarnessCoverageChip.test.tsx` | Tests/contracts | reviewed/no finding | Executed test + static review |
| `frontend/src/components/workspace/HarnessCoverageChip.tsx` | Components/runtime | reviewed/no finding | Static review + subsystem gate |
| `frontend/src/components/workspace/HumanReviewGate.tsx` | Components/runtime | reviewed/no finding | Static review + subsystem gate |
| `frontend/src/components/workspace/IdeaBacklog.test.tsx` | Tests/contracts | reviewed/no finding | Executed test + static review |
| `frontend/src/components/workspace/IdeaBacklog.tsx` | Components/runtime | reviewed/no finding | Static review + subsystem gate |
| `frontend/src/components/workspace/IncrementTimeline.test.tsx` | Tests/contracts | reviewed/no finding | Executed test + static review |
| `frontend/src/components/workspace/IncrementTimeline.tsx` | Components/runtime | reviewed/no finding | Static review + subsystem gate |
| `frontend/src/components/workspace/MarkdownRenderer.tsx` | Components/runtime | reviewed/no finding | Static review + subsystem gate |
| `frontend/src/components/workspace/ProblemStatementPanel.test.tsx` | Tests/contracts | reviewed/no finding | Executed test + static review |
| `frontend/src/components/workspace/ProblemStatementPanel.tsx` | Components/runtime | reviewed/no finding | Static review + subsystem gate |
| `frontend/src/components/workspace/QualityBadge.test.tsx` | Tests/contracts | reviewed/no finding | Executed test + static review |
| `frontend/src/components/workspace/QualityBadge.tsx` | Components/runtime | reviewed/no finding | Static review + subsystem gate |
| `frontend/src/components/workspace/RepoPicker.tsx` | Components/runtime | reviewed/no finding | Static review + subsystem gate |
| `frontend/src/components/workspace/ResearchConsentToggle.test.tsx` | Tests/contracts | reviewed/no finding | Executed test + static review |
| `frontend/src/components/workspace/ResearchConsentToggle.tsx` | Components/runtime | reviewed/no finding | Static review + subsystem gate |
| `frontend/src/components/workspace/SharePublicLinkModal.branded.test.tsx` | Tests/contracts | reviewed/no finding | Executed test + static review |
| `frontend/src/components/workspace/SharePublicLinkModal.tsx` | Components/runtime | reviewed/no finding | Static review + subsystem gate |
| `frontend/src/components/workspace/SpecClarificationModal.test.tsx` | Tests/contracts | reviewed/no finding | Executed test + static review |
| `frontend/src/components/workspace/SpecClarificationModal.tsx` | Components/runtime | reviewed/no finding | Static review + subsystem gate |
| `frontend/src/components/workspace/StageEditAction.tsx` | Components/runtime | reviewed/no finding | Static review + subsystem gate |
| `frontend/src/components/workspace/StageEditor.test.tsx` | Tests/contracts | reviewed/no finding | Executed test + static review |
| `frontend/src/components/workspace/StageEditor.tsx` | Components/runtime | reviewed/no finding | Static review + subsystem gate |
| `frontend/src/components/workspace/StageEmptyState.tsx` | Components/runtime | reviewed/no finding | Static review + subsystem gate |
| `frontend/src/components/workspace/StageNavigator.tsx` | Components/runtime | reviewed/no finding | Static review + subsystem gate |
| `frontend/src/components/workspace/StagedProgress.tsx` | Components/runtime | reviewed/no finding | Static review + subsystem gate |
| `frontend/src/components/workspace/StalenessWarning.tsx` | Components/runtime | reviewed/no finding | Static review + subsystem gate |
| `frontend/src/components/workspace/StoryboardToolbar.branded.test.tsx` | Tests/contracts | reviewed/no finding | Executed test + static review |
| `frontend/src/components/workspace/StoryboardToolbar.test.tsx` | Tests/contracts | reviewed/no finding | Executed test + static review |
| `frontend/src/components/workspace/StoryboardToolbar.tsx` | Components/runtime | reviewed/no finding | Static review + subsystem gate |
| `frontend/src/components/workspace/StreamingOverlay.branded.test.tsx` | Tests/contracts | reviewed/no finding | Executed test + static review |
| `frontend/src/components/workspace/StreamingOverlay.test.tsx` | Tests/contracts | reviewed/no finding | Executed test + static review |
| `frontend/src/components/workspace/StreamingOverlay.tsx` | Components/runtime | reviewed/no finding | Static review + subsystem gate |
| `frontend/src/components/workspace/SyncStatusBanner.tsx` | Components/runtime | reviewed/no finding | Static review + subsystem gate |
| `frontend/src/components/workspace/TaskCard.tsx` | Components/runtime | reviewed/no finding | Static review + subsystem gate |
| `frontend/src/components/workspace/TaskCompletionPanel.test.tsx` | Tests/contracts | reviewed/no finding | Executed test + static review |
| `frontend/src/components/workspace/TaskCompletionPanel.tsx` | Components/runtime | reviewed/no finding | Static review + subsystem gate |
| `frontend/src/components/workspace/TaskValidationPanel.tsx` | Components/runtime | reviewed/no finding | Static review + subsystem gate |
| `frontend/src/components/workspace/TasksBoard.tsx` | Components/runtime | reviewed/no finding | Static review + subsystem gate |
| `frontend/src/components/workspace/VersionHistoryPanel.test.tsx` | Tests/contracts | reviewed/no finding | Executed test + static review |
| `frontend/src/components/workspace/VersionHistoryPanel.tsx` | Components/runtime | reviewed/no finding | Static review + subsystem gate |
| `frontend/src/components/workspace/WorkspaceActionLockPanels.test.tsx` | Tests/contracts | reviewed/no finding | Executed test + static review |
| `frontend/src/components/workspace/useEtaEstimate.test.ts` | Tests/contracts | reviewed/no finding | Executed test + static review |
| `frontend/src/components/workspace/useEtaEstimate.ts` | Components/runtime | reviewed/no finding | Static review + subsystem gate |
| `frontend/src/config/.gitkeep` | Components/runtime | reviewed/no finding | Static review + subsystem gate |
| `frontend/src/config/featureFlags.ts` | Components/runtime | reviewed/no finding | Static review + subsystem gate |
| `frontend/src/config/starterWorkspaces.ts` | Components/runtime | reviewed/no finding | Static review + subsystem gate |
| `frontend/src/hooks/.gitkeep` | State/async | reviewed/no finding | Static review + subsystem gate |
| `frontend/src/hooks/useCredits.ts` | State/async | reviewed/no finding | Static review + subsystem gate |
| `frontend/src/hooks/useFocusTrap.ts` | State/async | reviewed/no finding | Static review + subsystem gate |
| `frontend/src/hooks/useGitHubSync.test.ts` | Tests/contracts | reviewed/no finding | Executed test + static review |
| `frontend/src/hooks/useGitHubSync.ts` | State/async | reviewed/no finding | Static review + subsystem gate |
| `frontend/src/hooks/useReconnectPoll.test.ts` | Tests/contracts | reviewed/no finding | Executed test + static review |
| `frontend/src/hooks/useReconnectPoll.ts` | State/async | reviewed/no finding | Static review + subsystem gate |
| `frontend/src/hooks/useScrollLock.ts` | State/async | reviewed/no finding | Static review + subsystem gate |
| `frontend/src/hooks/useStream.test.ts` | Tests/contracts | reviewed/no finding | Executed test + static review |
| `frontend/src/hooks/useStream.ts` | State/async | reviewed/no finding | Static review + subsystem gate |
| `frontend/src/index.css` | Styling/responsive | reviewed/no finding | Static review + subsystem gate |
| `frontend/src/main.tsx` | Components/runtime | reviewed/no finding | Static review + subsystem gate |
| `frontend/src/pages/.gitkeep` | Routes/pages | reviewed/no finding | Static review + subsystem gate |
| `frontend/src/pages/AuthCallback.tsx` | Routes/pages | reviewed/no finding | Static review + subsystem gate |
| `frontend/src/pages/Billing.tsx` | Routes/pages | reviewed/no finding | Static review + subsystem gate |
| `frontend/src/pages/Dashboard.tsx` | Routes/pages | reviewed/no finding | Static review + subsystem gate |
| `frontend/src/pages/GitHubHub.test.tsx` | Tests/contracts | reviewed/no finding | Executed test + static review |
| `frontend/src/pages/GitHubHub.tsx` | Routes/pages | reviewed/no finding | Static review + subsystem gate |
| `frontend/src/pages/Landing.tsx` | Routes/pages | reviewed/no finding | Static review + subsystem gate |
| `frontend/src/pages/LegalPrivacy.test.tsx` | Tests/contracts | reviewed/no finding | Executed test + static review |
| `frontend/src/pages/LegalPrivacy.tsx` | Routes/pages | reviewed/no finding | Static review + subsystem gate |
| `frontend/src/pages/LegalRetention.test.tsx` | Tests/contracts | reviewed/no finding | Executed test + static review |
| `frontend/src/pages/LegalRetention.tsx` | Routes/pages | reviewed/no finding | Static review + subsystem gate |
| `frontend/src/pages/LegalTerms.test.tsx` | Tests/contracts | reviewed/no finding | Executed test + static review |
| `frontend/src/pages/LegalTerms.tsx` | Routes/pages | reviewed/no finding | Static review + subsystem gate |
| `frontend/src/pages/PublicWorkspaceView.test.tsx` | Tests/contracts | reviewed/no finding | Executed test + static review |
| `frontend/src/pages/PublicWorkspaceView.tsx` | Routes/pages | reviewed/no finding | Static review + subsystem gate |
| `frontend/src/pages/Settings.test.tsx` | Tests/contracts | reviewed/no finding | Executed test + static review |
| `frontend/src/pages/Settings.tsx` | Routes/pages | reviewed/no finding | Static review + subsystem gate |
| `frontend/src/pages/Storyboard.test.tsx` | Tests/contracts | reviewed/no finding | Executed test + static review |
| `frontend/src/pages/Storyboard.tsx` | Routes/pages | reviewed/no finding | Static review + subsystem gate |
| `frontend/src/pages/StoryboardPublic.test.tsx` | Tests/contracts | reviewed/no finding | Executed test + static review |
| `frontend/src/pages/StoryboardPublic.tsx` | Routes/pages | reviewed/no finding | Static review + subsystem gate |
| `frontend/src/pages/Workspace.reconnect.test.ts` | Tests/contracts | reviewed/no finding | Executed test + static review |
| `frontend/src/pages/Workspace.remediation.test.tsx` | Tests/contracts | reviewed/no finding | Executed test + static review |
| `frontend/src/pages/Workspace.tsx` | Routes/pages | reviewed/no finding | Static review + subsystem gate |
| `frontend/src/pages/Workspace.version-history.test.tsx` | Tests/contracts | reviewed/no finding | Executed test + static review |
| `frontend/src/pages/WorkspaceGitHub.test.ts` | Tests/contracts | reviewed/no finding | Executed test + static review |
| `frontend/src/pages/WorkspaceGitHub.tsx` | Routes/pages | reviewed/no finding | Static review + subsystem gate |
| `frontend/src/pages/legalConstants.ts` | Routes/pages | reviewed/no finding | Static review + subsystem gate |
| `frontend/src/services/.gitkeep` | API/contracts | reviewed/no finding | Static review + subsystem gate |
| `frontend/src/services/api.config.test.ts` | Tests/contracts | reviewed/no finding | Executed test + static review |
| `frontend/src/services/api.csrf.test.ts` | Tests/contracts | reviewed/no finding | Executed test + static review |
| `frontend/src/services/api.errors.test.ts` | Tests/contracts | reviewed/no finding | Executed test + static review |
| `frontend/src/services/api.github.test.ts` | Tests/contracts | reviewed/no finding | Executed test + static review |
| `frontend/src/services/api.refresh.test.ts` | Tests/contracts | reviewed/no finding | Executed test + static review |
| `frontend/src/services/api.storyboard.test.ts` | Tests/contracts | reviewed/no finding | Executed test + static review |
| `frontend/src/services/api.ts` | API/contracts | reviewed/no finding | Static review + subsystem gate |
| `frontend/src/services/sseService.ts` | API/contracts | reviewed/no finding | Static review + subsystem gate |
| `frontend/src/store/.gitkeep` | State/async | reviewed/no finding | Static review + subsystem gate |
| `frontend/src/store/generationEstimatesStore.test.ts` | Tests/contracts | reviewed/no finding | Executed test + static review |
| `frontend/src/store/generationEstimatesStore.ts` | State/async | reviewed/no finding | Static review + subsystem gate |
| `frontend/src/store/stageStore.test.ts` | Tests/contracts | reviewed/no finding | Executed test + static review |
| `frontend/src/store/stageStore.ts` | State/async | reviewed/no finding | Static review + subsystem gate |
| `frontend/src/store/userStore.ts` | State/async | reviewed/no finding | Static review + subsystem gate |
| `frontend/src/store/workspaceStore.ts` | State/async | reviewed/no finding | Static review + subsystem gate |
| `frontend/src/types/.gitkeep` | API/contracts | reviewed/no finding | Static review + subsystem gate |
| `frontend/src/types/billing.ts` | API/contracts | reviewed/no finding | Static review + subsystem gate |
| `frontend/src/types/github.ts` | API/contracts | reviewed/no finding | Static review + subsystem gate |
| `frontend/src/types/publicShare.ts` | API/contracts | reviewed/no finding | Static review + subsystem gate |
| `frontend/src/types/retention.ts` | API/contracts | reviewed/no finding | Static review + subsystem gate |
| `frontend/src/types/stage.ts` | API/contracts | reviewed/no finding | Static review + subsystem gate |
| `frontend/src/types/storyboard.ts` | API/contracts | reviewed/no finding | Static review + subsystem gate |
| `frontend/src/types/template.ts` | API/contracts | reviewed/no finding | Static review + subsystem gate |
| `frontend/src/types/user.ts` | API/contracts | reviewed/no finding | Static review + subsystem gate |
| `frontend/src/types/workspace.ts` | API/contracts | reviewed/no finding | Static review + subsystem gate |
| `frontend/src/utils/constructionVerdict.test.ts` | Tests/contracts | reviewed/no finding | Executed test + static review |
| `frontend/src/utils/constructionVerdict.ts` | Components/runtime | reviewed/no finding | Static review + subsystem gate |
| `frontend/src/utils/errorPresentation.test.ts` | Tests/contracts | reviewed/no finding | Executed test + static review |
| `frontend/src/utils/errorPresentation.ts` | Components/runtime | reviewed/no finding | Static review + subsystem gate |
| `frontend/src/utils/github.ts` | Components/runtime | reviewed/no finding | Static review + subsystem gate |
| `frontend/src/utils/githubHub.test.ts` | Tests/contracts | reviewed/no finding | Executed test + static review |
| `frontend/src/utils/githubHub.ts` | Components/runtime | reviewed/no finding | Static review + subsystem gate |
| `frontend/src/utils/qualityGate.test.ts` | Tests/contracts | reviewed/no finding | Executed test + static review |
| `frontend/src/utils/qualityGate.ts` | Components/runtime | reviewed/no finding | Static review + subsystem gate |
| `frontend/src/utils/tasksParser.test.ts` | Tests/contracts | reviewed/no finding | Executed test + static review |
| `frontend/src/utils/tasksParser.ts` | Components/runtime | reviewed/no finding | Static review + subsystem gate |
| `frontend/tailwind.config.ts` | Styling/responsive | reviewed/no finding | Static review + subsystem gate |
| `frontend/tsconfig.json` | Components/runtime | reviewed/no finding | Static review + subsystem gate |
| `frontend/vercel.json` | Build/deploy | reviewed/no finding | Static review + subsystem gate |
| `frontend/vite.config.ts` | Build/deploy | reviewed/no finding | Static review + subsystem gate |
| `frontend/vitest.harness.config.ts` | Tests/contracts | reviewed/no finding | Executed test + static review |
| `backend/routers/__init__.py` | API/contracts | reviewed/no finding | OpenAPI/consumer boundary review |
| `backend/routers/auth.py` | API/contracts | reviewed/no finding | OpenAPI/consumer boundary review |
| `backend/routers/billing.py` | API/contracts | reviewed/no finding | OpenAPI/consumer boundary review |
| `backend/routers/credits.py` | API/contracts | reviewed/no finding | OpenAPI/consumer boundary review |
| `backend/routers/integrations.py` | API/contracts | reviewed/no finding | OpenAPI/consumer boundary review |
| `backend/routers/public.py` | API/contracts | reviewed/no finding | OpenAPI/consumer boundary review |
| `backend/routers/retention.py` | API/contracts | reviewed/no finding | OpenAPI/consumer boundary review |
| `backend/routers/stage.py` | API/contracts | reviewed/no finding | OpenAPI/consumer boundary review |
| `backend/routers/storyboards.py` | API/contracts | reviewed/no finding | OpenAPI/consumer boundary review |
| `backend/routers/templates.py` | API/contracts | reviewed/no finding | OpenAPI/consumer boundary review |
| `backend/routers/workspace.py` | API/contracts | reviewed/no finding | OpenAPI/consumer boundary review |
| `backend/schemas/__init__.py` | API/contracts | reviewed/no finding | OpenAPI/consumer boundary review |
| `backend/schemas/auth.py` | API/contracts | reviewed/no finding | OpenAPI/consumer boundary review |
| `backend/schemas/billing.py` | API/contracts | reviewed/no finding | OpenAPI/consumer boundary review |
| `backend/schemas/common.py` | API/contracts | reviewed/no finding | OpenAPI/consumer boundary review |
| `backend/schemas/credits.py` | API/contracts | reviewed/no finding | OpenAPI/consumer boundary review |
| `backend/schemas/github.py` | API/contracts | reviewed/no finding | OpenAPI/consumer boundary review |
| `backend/schemas/increment.py` | API/contracts | reviewed/no finding | OpenAPI/consumer boundary review |
| `backend/schemas/integration.py` | API/contracts | reviewed/no finding | OpenAPI/consumer boundary review |
| `backend/schemas/retention.py` | API/contracts | reviewed/no finding | OpenAPI/consumer boundary review |
| `backend/schemas/stage.py` | API/contracts | reviewed/no finding | OpenAPI/consumer boundary review |
| `backend/schemas/storyboard.py` | API/contracts | reviewed/no finding | OpenAPI/consumer boundary review |
| `backend/schemas/template.py` | API/contracts | reviewed/no finding | OpenAPI/consumer boundary review |
| `backend/schemas/workspace.py` | API/contracts | reviewed/no finding | OpenAPI/consumer boundary review |
