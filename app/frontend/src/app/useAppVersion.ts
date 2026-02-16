import { useQuery } from '@tanstack/react-query'
import { getAppVersion } from '../api'

export function useAppVersion() {
  const appVersion = useQuery({
    queryKey: ['app-version'],
    queryFn: () => getAppVersion(),
    retry: 1,
  })

  return {
    frontendVersion: import.meta.env.VITE_APP_VERSION ?? 'dev',
    backendVersion: appVersion.data?.backend_version ?? 'unknown',
    backendBuild: appVersion.data?.backend_build ?? null,
    backendDeployedAtUtc: appVersion.data?.deployed_at_utc ?? null,
  }
}
