import { io } from "socket.io-client"
import { ref } from "vue"

// Same-origin connection: SocketIO rides over the page's host so it shares
// the browser's HTTP connection pool with the page + REST API. Avoids
// cross-origin pool fragmentation when many windows are open simultaneously.
// In dev: Vite proxies /wss -> 127.0.0.1:15100. In preview: same.
// In production behind nginx/etc: forward /wss -> backend.
const BACKEND_URL = `${window.location.protocol}//${window.location.host}`

export const connected = ref(false)
export const socket = io(BACKEND_URL, {
  path: "/wss",
  transports: ["websocket", "polling"],
  reconnection: true,
  reconnectionDelay: 2000,
})

socket.on("connect", () => { connected.value = true })
socket.on("disconnect", () => { connected.value = false })

export default socket
