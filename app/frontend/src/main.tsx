import React from 'react'
import { createRoot } from 'react-dom/client'
import AppRoot from './App'
import 'driver.js/dist/driver.css'
import 'react-diff-view/style/index.css'
import './styles.css'

createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <AppRoot />
  </React.StrictMode>
)
