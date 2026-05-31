import { createApp, nextTick } from "vue"
import TDesign from "tdesign-vue-next"
import "tdesign-vue-next/es/style/index.css"
import App from "./App.vue"
import router from "./router"

// Tell the splash we made it past the heavy module-evaluation phase.
// (Anything imported above is now parsed + linked.)
window.__clawavcStage && window.__clawavcStage("parse")

const app = createApp(App)
app.use(TDesign)         // synchronous register of every TDesign component
app.use(router)

window.__clawavcStage && window.__clawavcStage("mounting")
app.mount("#app")
window.__clawavcStage && window.__clawavcStage("mounted")

// Hide the splash on the next frame so Vue's first paint and the splash
// fade overlap — the user never sees a blank moment between the two.
nextTick(() => {
  if (typeof window.__clawavcReady === "function") window.__clawavcReady()
})
