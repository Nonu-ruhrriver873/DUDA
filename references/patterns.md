# DUDA Pattern Reference
> Risk patterns and fix patterns by isolation type

---

## Type A — Platform-Derivative (Platform → Tenant)

**Structure:** An upper platform (Platform/System) defines features, and lower derivatives (Organization/Tenant/Store) inherit, restrict, or extend them.

**Example:** Platform → Organization HQ → Brand → Store

---

### A-1. Direct Component Copy-Paste (Most Common)

**Risk Pattern:**
```tsx
// ❌ tenant/components/ConfigManager.tsx
// Platform's config management component copied directly
import { ConfigTable } from "@/platform/components/ConfigTable"
import { masterConfigStore } from "@/platform/stores/masterConfigStore"

export function TenantConfigManager() {
  // Direct access to platform-only master data
  const { configs } = masterConfigStore()
  return <ConfigTable data={configs} showPlatformFields />
}
```

**Fix Pattern — Strategy 2 Adapter:**
```tsx
// ✅ tenant/components/ConfigViewer.tsx
// Receives only permitted data through API, not platform store
import { useTenantConfig } from "@/tenant/hooks/useTenantConfig"

export function TenantConfigViewer() {
  // Tenant-specific API hook — platform-only fields not exposed
  const { config, isLoading } = useTenantConfig()
  return <ConfigTable data={config} />  // no showPlatformFields
}
```

---

### A-2. Hardcoded Upper-Only Identifiers

**Risk Pattern:**
```ts
// ❌ tenant/utils/roleCheck.ts
function canEditConfig(user: User) {
  // "platform_admin" is a platform-only role — must not exist in tenant layer
  return user.role === "platform_admin" || user.role === "tenant_manager"
}
```

**Fix Pattern:**
```ts
// ✅ tenant/utils/roleCheck.ts
function canEditConfig(user: User) {
  // Only reference roles that exist in the tenant layer
  return user.role === "tenant_manager" || user.role === "brand_manager"
}
```

---

### A-3. Direct Use of Upper-Only Environment Variables

**Risk Pattern:**
```ts
// ❌ tenant/lib/api.ts
const client = createClient(
  process.env.PLATFORM_SUPABASE_URL,  // Platform-only DB
  process.env.PLATFORM_ANON_KEY
)
```

**Fix Pattern:**
```ts
// ✅ tenant/lib/api.ts
const client = createClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL,  // Tenant-specific or shared DB
  process.env.NEXT_PUBLIC_ANON_KEY
)
```

---

## Type B — Multi-tenant

**Structure:** Multiple tenants (companies/organizations) share the same codebase but isolate data. Enforced via RLS (Row Level Security) or middleware.

---

### B-1. DB Queries Without Tenant Identifier (Data Exposure Risk)

**Risk Pattern:**
```ts
// ❌ api/menu.ts
async function getMenuItems() {
  const { data } = await supabase
    .from("menu_items")
    .select("*")
  // ← No org_id filter → all tenant data exposed
  return data
}
```

**Fix Pattern — Explicit Filter:**
```ts
// ✅ api/menu.ts
async function getMenuItems(orgId: string) {
  const { data } = await supabase
    .from("menu_items")
    .select("*")
    .eq("org_id", orgId)  // ← Tenant identifier required
  return data
}
```

**Fix Pattern — RLS-based (Safer):**
```sql
-- migrations/xxx_rls_menu.sql
ALTER TABLE menu_items ENABLE ROW LEVEL SECURITY;

CREATE POLICY "tenant_isolation" ON menu_items
  USING (org_id = auth.jwt() ->> 'org_id');
-- With RLS, queries auto-filter even without .eq("org_id")
```

---

### B-2. Missing Tenant Context Propagation

**Risk Pattern:**
```ts
// ❌ components/Dashboard.tsx
function Dashboard() {
  // Only userId, no orgId
  const { userId } = useAuth()
  const data = useDashboardData(userId)  // Which tenant's data?
}
```

**Fix Pattern:**
```ts
// ✅ components/Dashboard.tsx
function Dashboard() {
  const { userId, orgId } = useAuth()  // orgId required
  const data = useDashboardData({ userId, orgId })
}
```

---

### B-3. Shared Cache Without Tenant Key

**Risk Pattern:**
```ts
// ❌ lib/cache.ts
const cacheKey = `menu:${menuId}`
// ← No orgId → tenant A's cache could be served to tenant B
```

**Fix Pattern:**
```ts
// ✅ lib/cache.ts
const cacheKey = `menu:${orgId}:${menuId}`
// ← Tenant identifier included in cache key
```

---

## Type C — Monorepo Boundary

**Structure:** Code isolation between apps/ in Turborepo/Nx monorepos. Only packages/ are shared.

---

### C-1. Direct Import Between apps/

**Risk Pattern:**
```ts
// ❌ apps/tenant/components/Button.tsx
import { PlatformButton } from "../../platform/components/Button"
// ← Direct cross-app import — circular build dependency risk
```

**Fix Pattern:**
```ts
// ✅ packages/ui/components/Button.tsx (extracted to shared package)
export function Button({ variant, ...props }) { ... }

// ✅ apps/platform/components/PlatformButton.tsx
import { Button } from "@myapp/ui"
export function PlatformButton() { return <Button variant="platform" /> }

// ✅ apps/tenant/components/TenantButton.tsx
import { Button } from "@myapp/ui"
export function TenantButton() { return <Button variant="tenant" /> }
```

---

### C-2. Package Boundary Bypass

**Risk Pattern:**
```ts
// ❌ apps/tenant/lib/types.ts
// Shared type defined inside apps/ instead of packages/
export type MenuItem = { id: string; orgId: string; ... }

// apps/platform imports this → cross-app dependency
import type { MenuItem } from "../../tenant/lib/types"
```

**Fix Pattern:**
```ts
// ✅ packages/types/src/menu.ts
export type MenuItem = { id: string; orgId: string; ... }

// Both apps import from package
import type { MenuItem } from "@myapp/types"
```

---

### C-3. Internal Package Version Mismatch

**Risk Pattern:**
```json
// ❌ apps/tenant/package.json
{ "@myapp/ui": "^1.0.0" }

// ❌ apps/platform/package.json
{ "@myapp/ui": "^2.0.0" }
// ← Same package, different versions → runtime mismatch
```

**Fix Pattern (turbo.json / pnpm workspace):**
```json
// ✅ Root package.json — pin version
{
  "pnpm": {
    "overrides": { "@myapp/ui": "2.1.0" }
  }
}
```

---

## Type D — Microservice Boundary

**Structure:** Data and code isolation between independently deployed services. Only API boundaries are permitted.

---

### D-1. Direct DB Access Across Services

**Risk Pattern:**
```ts
// ❌ order-service/src/lib/inventory.ts
// Directly accessing inventory service's database
const { data } = await inventorySupabase
  .from("stock_items")
  .select("quantity")
```

**Fix Pattern — API Boundary:**
```ts
// ✅ order-service/src/lib/inventory.ts
const response = await fetch(`${INVENTORY_SERVICE_URL}/api/stock/${itemId}`)
const { quantity } = await response.json()
```

---

### D-2. API Communication Without Shared Types

**Risk Pattern:**
```ts
// ❌ service-a
const result: any = await fetch("/api/order")  // No type

// ❌ service-b
return { orderId: 1, total: "10000" }  // string or number? unclear
```

**Fix Pattern — Shared Type Package:**
```ts
// ✅ packages/api-contracts/src/order.ts
export type OrderResponse = {
  orderId: number
  total: number  // explicit type
  currency: "KRW" | "USD"
}

// Both services import
import type { OrderResponse } from "@myapp/api-contracts"
```

---

### D-3. Shared State Across Service Boundaries

**Risk Pattern:**
```ts
// ❌ order-service/src/lib/session.ts
import { userSession } from "@/auth-service/stores/session"
// Direct store import from another service — violates service boundary
```

**Fix Pattern — API-based State Query:**
```ts
// ✅ order-service/src/lib/session.ts
async function getUserSession(token: string) {
  const res = await fetch(`${AUTH_SERVICE_URL}/api/session`, {
    headers: { Authorization: `Bearer ${token}` }
  })
  return res.json()
}
```

---

## Common — UNVERIFIABLE Handling Pattern

Dynamic imports, runtime role checks, and other patterns that resist static analysis.

**Risk Pattern:**
```ts
// Patterns that DUDA tags as [UNVERIFIABLE]

// 1. Dynamic import
const module = await import(`@/${userRole}/components/Dashboard`)

// 2. Runtime role check
if (user.role === "platform_admin") {
  // platform-only UI rendering — not statically traceable
}

// 3. Env var branching
const Component = process.env.APP_MODE === "platform"
  ? PlatformDashboard
  : TenantDashboard
```

**Fix Pattern — Convert to Explicit Branching:**
```ts
// ✅ Convert to statically analyzable structure
// [UPPER-ONLY] PlatformDashboard exists only in platform layer
// → DUDA can tag accurately

// apps/platform/pages/dashboard.tsx
import { PlatformDashboard } from "@/platform/components/PlatformDashboard"
export default PlatformDashboard

// apps/tenant/pages/dashboard.tsx
import { TenantDashboard } from "@/tenant/components/TenantDashboard"
export default TenantDashboard
```

---

## Diagnostic Checklists

### Before Transplant (TRANSPLANT)

```
□ All imports in source file are tagged
□ Any [UPPER-ONLY] items present → consider Strategy 4
□ DB queries have tenant identifiers
□ Any dynamic import / runtime branching → manual review
□ No conflict with transplant-deny list
□ Destination layer is contamination-free
```

### When Contamination is Suspected (AUDIT)

```
□ Which layer shows the symptom
□ Which layer's data/features are incorrectly visible
□ When did it start (recent operation history)
□ Type B: Do DB queries have org_id filter?
□ Type A: Does lower layer import upper-only paths?
□ Type C: Is there direct import between apps/?
□ Type D: Is there direct DB access across services?
```

### Post-Recovery Verification

```
□ grep confirms contamination path → 0 results
□ Symptom no longer reproducible on actual screen
□ Verified with different tenant account → data properly isolated
□ DUDA_MAP partial refresh completed
□ Memory record saved
```
