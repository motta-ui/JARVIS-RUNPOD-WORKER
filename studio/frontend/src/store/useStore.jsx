import { createContext, useContext, useEffect, useState } from 'react'
import { api } from '../api/client.js'

const StudioContext = createContext(null)

export function StudioProvider({ children }) {
  const [online, setOnline] = useState(false)
  const [currentEngine, setCurrentEngine] = useState('mock')

  useEffect(() => {
    let mounted = true
    const check = () => {
      api.health()
        .then(() => mounted && setOnline(true))
        .catch(() => mounted && setOnline(false))
    }
    check()
    const interval = setInterval(check, 8000)
    return () => {
      mounted = false
      clearInterval(interval)
    }
  }, [])

  return (
    <StudioContext.Provider value={{ online, currentEngine, setCurrentEngine }}>
      {children}
    </StudioContext.Provider>
  )
}

export function useStudio() {
  const ctx = useContext(StudioContext)
  if (!ctx) throw new Error('useStudio deve ser usado dentro de StudioProvider')
  return ctx
}
