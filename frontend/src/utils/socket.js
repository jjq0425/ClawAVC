import { io } from "socket.io-client"
import { ref } from "vue"

const BACKEND_URL = window.location.hostname === "localhost"
  ? "http://127.0.0.1:15100"
  : `http://${window.location.hostname}:15100`

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
