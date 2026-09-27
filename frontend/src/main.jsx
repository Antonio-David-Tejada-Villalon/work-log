import React from 'react'
import { createRoot } from 'react-dom/client'
import './custom.scss'
import 'bootstrap-icons/font/bootstrap-icons.css'
import './app.css'
import { initTheme } from './theme'
import App from './App'

initTheme()
createRoot(document.getElementById('root')).render(<React.StrictMode><App /></React.StrictMode>)
