export type FeishuNativeUser = {
  id: string
  name?: string
}

export type FeishuNativeDepartment = {
  id: string
  name: string
}

export type FeishuNativeRuntime = {
  available: boolean
  mode: 'sdk' | 'mock'
}

let sdkLoadPromise: Promise<any | null> | null = null

async function loadBaseSdk() {
  if (!sdkLoadPromise) {
    sdkLoadPromise = import('@lark-base-open/js-sdk')
      .then((mod) => mod)
      .catch(() => null)
  }
  return sdkLoadPromise
}

export async function feishuNativeRuntime(): Promise<FeishuNativeRuntime> {
  const mod = await loadBaseSdk()
  return { available: Boolean(mod?.bitable), mode: mod?.bitable ? 'sdk' : 'mock' }
}

export async function selectFeishuUser(): Promise<FeishuNativeUser | null> {
  const runtime = await feishuNativeRuntime()
  if (runtime.mode === 'sdk') {
    // The Base JS SDK is loaded and chunked here. A real Feishu/Lark host can replace
    // this MVP bridge with native contact picker APIs without changing admin form payloads.
  }
  const value = window.prompt('输入飞书用户 open_id / user_id（当前为本地 Mock 选择器）')
  const id = String(value || '').trim()
  return id ? { id } : null
}

export async function selectFeishuDepartments(): Promise<FeishuNativeDepartment[]> {
  const runtime = await feishuNativeRuntime()
  if (runtime.mode === 'sdk') {
    // Keep this adapter side-effect free: selected department display names are used only
    // to match/create local岗位组; no Feishu metadata is persisted to user records.
  }
  const value = window.prompt('输入飞书部门名称，多个用逗号分隔（当前为本地 Mock 选择器）')
  return String(value || '')
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean)
    .map((name) => ({ id: name, name }))
}
