import { createMockServices } from './mock'

// Views use the service contract. Real API integration is a separate task.
const mode = new URLSearchParams(window.location.search).get('demo')
export const services = createMockServices({ empty: mode === 'empty', failLoad: mode === 'error' })
