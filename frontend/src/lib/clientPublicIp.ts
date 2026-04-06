/**
 * Best-effort public IPv4/IPv6 as seen from the internet (browser cannot read MAC or LAN MAC).
 * Uses ipify.org (HTTPS, CORS-friendly for browser apps).
 */
export async function fetchClientPublicIp(): Promise<string | null> {
  const ctrl = new AbortController();
  const t = window.setTimeout(() => ctrl.abort(), 12_000);
  try {
    const res = await fetch('https://api.ipify.org?format=json', { signal: ctrl.signal });
    if (!res.ok) return null;
    const j = (await res.json()) as { ip?: string };
    const ip = typeof j.ip === 'string' ? j.ip.trim() : '';
    return ip || null;
  } catch {
    return null;
  } finally {
    window.clearTimeout(t);
  }
}
