import { createRouter, createWebHistory } from "vue-router"

const routes = [
  {
    path: "/login",
    name: "Login",
    component: () => import("../views/LoginPage.vue"),
    meta: { requiresAuth: false },
  },
  {
    path: "/",
    name: "Home",
    component: () => import("../views/HomePage.vue"),
    meta: { requiresAuth: true },
  },
  {
    path: "/monitor",
    name: "Monitor",
    component: () => import("../views/MonitorPage.vue"),
    meta: { requiresAuth: true },
  },
  {
    path: "/attack",
    name: "Attack",
    component: () => import("../views/AttackPage.vue"),
    meta: { requiresAuth: true },
  },
  {
    path: "/policy",
    name: "Policy",
    component: () => import("../views/PolicyPage.vue"),
    meta: { requiresAuth: true },
  },
  {
    path: "/database",
    name: "Database",
    component: () => import("../views/DatabasePage.vue"),
    meta: { requiresAuth: true },
  },
  {
    path: "/export",
    name: "Export",
    component: () => import("../views/ExportPage.vue"),
    meta: { requiresAuth: true },
  },
  {
    path: "/api-docs",
    name: "ApiDocs",
    component: () => import("../views/ApiDocsPage.vue"),
    meta: { requiresAuth: true },
  },
  {
    path: "/navigator",
    name: "Navigator",
    component: () => import("../views/NavigatorPage.vue"),
    meta: { requiresAuth: true },
  },
  {
    path: "/settings",
    name: "Settings",
    component: () => import("../views/SettingsPage.vue"),
    meta: { requiresAuth: true },
  },
  {
    path: "/replay",
    name: "Replay",
    component: () => import("../views/ReplayPage.vue"),
    meta: { requiresAuth: true },
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach((to, from, next) => {
  if (!to.meta.requiresAuth) return next()
  const token = sessionStorage.getItem("clawavc_verified_key")
  if (token) return next()
  next({ name: "Login" })
})

export default router
