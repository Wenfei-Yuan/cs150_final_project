import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { Toaster } from '@/components/ui/sonner'
import UploadPage from '@/pages/UploadPage'
import IntroPage from '@/pages/IntroPage'
import ReadPage from '@/pages/ReadPage'
import LearningTestPage from '@/pages/LearningTestPage'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<UploadPage />} />
        <Route path="/intro/:sessionId" element={<IntroPage />} />
        <Route path="/read/:sessionId" element={<ReadPage />} />
        <Route path="/quiz/:sessionId" element={<LearningTestPage />} />
      </Routes>
      <Toaster position="bottom-right" />
    </BrowserRouter>
  )
}
