"use client"

import { useState, useEffect } from "react"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { Upload, Play, ExternalLink } from "lucide-react"
import FileUpload from "@/components/file-upload"
import ClipList from "@/components/clip-list"
import LoadingAnimation from "@/components/loading-animation"
import VideoPreview from "@/components/video-preview"
import { Checkbox } from "@/components/ui/checkbox"
import { Label } from "@/components/ui/label"
import { config } from "@/config"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"

export type VideoClip = {
  id: string
  name: string
  type: string
  size: number
  url: string
  file?: File
}

interface VerificationDetails {
  verification_id: string
  chain_url: string
  timestamp: string
  is_valid: boolean
}

interface TaskStatus {
  status: "processing" | "completed" | "failed"
  message: string
  video_url?: string
  result?: string
  verification?: VerificationDetails
}

export default function VideoEditor() {
  const [prompt, setPrompt] = useState("")
  const [clips, setClips] = useState<VideoClip[]>([])
  const [isProcessing, setIsProcessing] = useState(false)
  const [processedVideo, setProcessedVideo] = useState<string | null>(null)
  const [isLocalMode, setIsLocalMode] = useState(config.processing.defaultLocalMode)
  const [error, setError] = useState<string | null>(null)
  const [taskId, setTaskId] = useState<string | null>(null)
  const [statusMessage, setStatusMessage] = useState<string | null>(null)
  const [processingProgress, setProcessingProgress] = useState<number>(0)
  const [verificationDetails, setVerificationDetails] = useState<VerificationDetails | null>(null)

  // Poll for task status when taskId changes
  useEffect(() => {
    if (!taskId) return
    
    const pollInterval = setInterval(async () => {
      try {
        const response = await fetch(`/api/task-status/${taskId}`)
        
        if (!response.ok) {
          throw new Error("Failed to fetch task status")
        }
        
        const taskStatus: TaskStatus = await response.json()
        setStatusMessage(taskStatus.message)
        
        // Set a fake progress percentage based on messages
        if (taskStatus.status === "processing") {
          // Increment progress to show something is happening
          setProcessingProgress(prev => Math.min(prev + 5, 95))
        }
        
        if (taskStatus.status === "completed") {
          clearInterval(pollInterval)
          setIsProcessing(false)
          setProcessingProgress(100)
          if (taskStatus.video_url) {
            setProcessedVideo(taskStatus.video_url)
          }
        } else if (taskStatus.status === "failed") {
          clearInterval(pollInterval)
          setIsProcessing(false)
          setError(taskStatus.message)
        }
      } catch (err) {
        console.error("Error polling task status:", err)
      }
    }, config.api.pollingInterval) // Poll interval from config
    
    return () => clearInterval(pollInterval)
  }, [taskId])

  const handleFileUpload = (files: FileList) => {
    const newClips = Array.from(files).map((file) => {
      return {
        id: Math.random().toString(36).substring(7),
        name: file.name,
        type: file.type.split("/")[1],
        size: file.size,
        url: URL.createObjectURL(file),
        file: file,
      }
    })

    setClips([...clips, ...newClips])
  }

  const removeClip = (id: string) => {
    setClips(clips.filter((clip) => clip.id !== id))
  }

  const processVideo = async () => {
    if (clips.length === 0) return
    setError(null)
    setIsProcessing(true)
    setProcessedVideo(null)
    setTaskId(null)
    setStatusMessage(null)
    setProcessingProgress(0)
    setVerificationDetails(null)

    try {
      // Create FormData to send files to the backend
      const formData = new FormData()
      formData.append("prompt", prompt)
      
      // Add all video files
      clips.forEach((clip, index) => {
        if (clip.file) {
          formData.append("videos", clip.file)
        }
      })

      // Call the backend API
      const response = await fetch("/api/process-video", {
        method: "POST",
        body: formData
      })

      if (!response.ok) {
        const errorData = await response.json()
        throw new Error(errorData.error || "Failed to process video")
      }

      const data = await response.json()
      setIsProcessing(false)
      
      // Show the processed video
      if (data.output_path) {
        setProcessedVideo(`/test_outputs/${data.output_path.split('/').pop()}`)
      }

      // Set verification details if present
      if (data.verification) {
        setVerificationDetails(data.verification)
      }
    } catch (err) {
      console.error("Error processing video:", err)
      setError(err instanceof Error ? err.message : "An unknown error occurred")
      setIsProcessing(false)
    }
  }

  return (
    <div className="container mx-auto px-4 py-12 max-w-6xl">
      <div className="mb-8">
        <h1 className="text-4xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-purple-400 via-cyan-500 to-emerald-400 mb-2">
          AI Video Editor
        </h1>
        <p className="text-zinc-400">Upload your video, describe your edits, and let AI do the magic</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
        <div className="space-y-6">
          <div className="space-y-2">
            <h2 className="text-xl font-semibold text-white">Describe Your Edit</h2>
            <Textarea
              placeholder="Describe how you want your video to be edited..."
              className="h-32 bg-zinc-900 border-zinc-800 focus-visible:ring-purple-500"
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
            />
          </div>

          <div className="space-y-2">
            <h2 className="text-xl font-semibold text-white">Upload Video</h2>
            <FileUpload onUpload={handleFileUpload} />
          </div>

          {clips.length > 0 && (
            <div className="space-y-2">
              <h2 className="text-xl font-semibold text-white">Your Videos</h2>
              <ClipList clips={clips} onRemove={removeClip} />
            </div>
          )}

          <Button
            onClick={processVideo}
            disabled={clips.length === 0 || prompt.trim() === "" || isProcessing}
            className="w-full bg-gradient-to-r from-purple-600 to-blue-600 hover:from-purple-700 hover:to-blue-700 text-white"
          >
            <Play className="mr-2 h-4 w-4" />
            Process Video
          </Button>
          
          {verificationDetails && (
            <Alert className="bg-emerald-500/10 border-emerald-500/20 text-emerald-500">
              <AlertTitle className="flex items-center gap-2">
                <span>✓ LLM Response Verified On-Chain</span>
              </AlertTitle>
              <AlertDescription className="mt-2">
                <div className="space-y-2">
                  <p>Verification ID: {verificationDetails.verification_id}</p>
                  <p>Timestamp: {new Date(verificationDetails.timestamp).toLocaleString()}</p>
                  <a
                    href={verificationDetails.chain_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex items-center gap-2 text-emerald-500 hover:text-emerald-400"
                  >
                    View on Chain <ExternalLink className="h-4 w-4" />
                  </a>
                </div>
              </AlertDescription>
            </Alert>
          )}

          {error && (
            <div className="text-red-500 text-sm mt-2 p-2 bg-red-500/10 rounded border border-red-500/20">
              {error}
            </div>
          )}
        </div>

        <div className="bg-zinc-900 rounded-xl border border-zinc-800 p-6 h-[500px] flex items-center justify-center">
          {isProcessing ? (
            <LoadingAnimation statusMessage={statusMessage} progress={processingProgress} />
          ) : processedVideo ? (
            <VideoPreview videoUrl={processedVideo} />
          ) : (
            <div className="text-center text-zinc-500">
              <Upload className="h-16 w-16 mx-auto mb-4 opacity-50" />
              <p>Upload a video and process to see the result here</p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

