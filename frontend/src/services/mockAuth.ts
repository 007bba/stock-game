export interface MockAuthUser {
  id: string
  email: string
  displayName: string
  createdAt: string
}

interface MockAuthRecord extends MockAuthUser {
  password: string
}

const USERS_KEY = 'stock-game:mock-auth-users'

function normalizeEmail(email: string): string {
  return email.trim().toLowerCase()
}

function wait(ms: number): Promise<void> {
  return new Promise((resolve) => {
    setTimeout(resolve, ms)
  })
}

function getId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }
  return `mock-${Date.now()}`
}

function parseStoredUsers(): Record<string, MockAuthRecord> {
  if (typeof window === 'undefined') {
    return {}
  }

  try {
    const raw = localStorage.getItem(USERS_KEY)
    if (!raw) {
      return {}
    }
    const parsed = JSON.parse(raw) as Record<string, MockAuthRecord>
    return parsed ?? {}
  } catch {
    return {}
  }
}

function saveUsers(users: Record<string, MockAuthRecord>): void {
  if (typeof window === 'undefined') {
    return
  }
  localStorage.setItem(USERS_KEY, JSON.stringify(users))
}

function toUser(record: MockAuthRecord): MockAuthUser {
  return {
    id: record.id,
    email: record.email,
    displayName: record.displayName,
    createdAt: record.createdAt,
  }
}

export async function registerMockUser(params: {
  email: string
  password: string
  displayName?: string
}): Promise<MockAuthUser> {
  await wait(450)

  const users = parseStoredUsers()
  const email = normalizeEmail(params.email)
  if (users[email]) {
    throw new Error('该邮箱已注册，请直接登录')
  }

  const inferredName = email.split('@')[0] || 'player'
  const record: MockAuthRecord = {
    id: getId(),
    email,
    password: params.password,
    displayName: params.displayName?.trim() || inferredName,
    createdAt: new Date().toISOString(),
  }

  users[email] = record
  saveUsers(users)

  return toUser(record)
}

export async function loginMockUser(params: {
  email: string
  password: string
}): Promise<MockAuthUser> {
  await wait(350)

  const users = parseStoredUsers()
  const email = normalizeEmail(params.email)
  const record = users[email]

  if (!record) {
    throw new Error('账号不存在，请先注册')
  }
  if (record.password !== params.password) {
    throw new Error('密码错误，请重试')
  }

  return toUser(record)
}
