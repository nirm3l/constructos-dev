import React from 'react'
import { createRoot } from 'react-dom/client'
import AppRoot from './App'
import 'driver.js/dist/driver.css'
import './styles.css'

createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <AppRoot />
  </React.StrictMode>
)
