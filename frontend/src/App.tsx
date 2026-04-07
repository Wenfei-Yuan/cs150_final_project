import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { Toaster } from '@/components/ui/sonner'
import UploadPage from '@/pages/UploadPage'
import ReadPage from '@/pages/ReadPage'


export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<UploadPage />} />
        <Route path="/read/:sessionId" element={<ReadPage />} />

      </Routes>
      <Toaster position="bottom-right" />
    </BrowserRouter>
  )
}
