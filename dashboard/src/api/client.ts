import axios from 'axios'
import { API_BASE } from '../lib/constants'

const client = axios.create({ baseURL: API_BASE, timeout: 10_000 })

client.interceptors.response.use(
  r => r,
  err => {
    console.error('[API]', err.response?.status, err.config?.url, err.message)
    return Promise.reject(err)
  }
)

export default client
