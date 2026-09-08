import { Routes, Route, Navigate } from 'react-router-dom'
import { StudioProvider } from './store/useStore.jsx'
import { ToastProvider } from './store/useToast.jsx'
import ErrorBoundary from './components/ErrorBoundary.jsx'
import Layout from './components/layout/Layout.jsx'
import Home from './pages/Home.jsx'
import VideoStudio from './pages/VideoStudio.jsx'
import ImageStudio from './pages/ImageStudio.jsx'
import AudioStudio from './pages/AudioStudio.jsx'
import MotionStudio from './pages/MotionStudio.jsx'
import Gallery from './pages/Gallery.jsx'
import Assets from './pages/Assets.jsx'
import Projects from './pages/Projects.jsx'
import LoraManager from './pages/LoraManager.jsx'
import Settings from './pages/Settings.jsx'
import Engines from './pages/Engines.jsx'
import Cloud from './pages/Cloud.jsx'
import Placeholder from './pages/UpdatesPlaceholder.jsx'

export default function App() {
  return (
    <ErrorBoundary>
      <ToastProvider>
        <StudioProvider>
          <Layout>
            <Routes>
              <Route path="/" element={<Home />} />

              <Route path="/create/image" element={<ImageStudio />} />
              <Route path="/create/video" element={<VideoStudio />} />
              <Route path="/create/audio" element={<AudioStudio />} />
              <Route path="/create/motion" element={<MotionStudio />} />

              <Route path="/library/assets" element={<Assets />} />
              <Route path="/library/gallery" element={<Gallery />} />
              <Route path="/library/projects" element={<Projects />} />
              <Route path="/library/loras" element={<LoraManager />} />

              <Route path="/system/settings" element={<Settings />} />
              <Route path="/system/engines" element={<Engines />} />
              <Route path="/system/cloud" element={<Cloud />} />
              <Route path="/system/updates" element={<Placeholder />} />

              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </Layout>
        </StudioProvider>
      </ToastProvider>
    </ErrorBoundary>
  )
}
