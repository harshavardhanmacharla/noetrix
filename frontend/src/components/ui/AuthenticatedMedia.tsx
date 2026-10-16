import React, { useEffect, useState } from 'react';
import { Camera, Film, AlertTriangle } from 'lucide-react';
import { LoadingSpinner } from './LoadingSpinner';
import { reportsApi } from '../../api/reports';

interface AuthenticatedMediaProps {
  artifactId?: string;
  filePath?: string;
  className?: string;
}

interface AuthenticatedImageProps extends AuthenticatedMediaProps {
  alt: string;
}

export const AuthenticatedImage: React.FC<AuthenticatedImageProps> = ({
  artifactId,
  filePath,
  alt,
  className = '',
}) => {
  const [blobUrl, setBlobUrl] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!artifactId && !filePath) {
      setBlobUrl(null);
      setError(null);
      setLoading(false);
      return;
    }

    let isMounted = true;
    let currentObjectUrl: string | null = null;

    setLoading(true);
    setError(null);

    reportsApi
      .fetchArtifactBlob({ id: artifactId, path: filePath })
      .then((blob) => {
        if (isMounted) {
          currentObjectUrl = URL.createObjectURL(blob);
          setBlobUrl(currentObjectUrl);
          setLoading(false);
        }
      })
      .catch((err: unknown) => {
        if (isMounted) {
          const message = err instanceof Error ? err.message : 'Failed to load image';
          setError(message);
          setLoading(false);
        }
      });

    return () => {
      isMounted = false;
      if (currentObjectUrl) {
        URL.revokeObjectURL(currentObjectUrl);
      }
    };
  }, [artifactId, filePath]);

  if (loading) {
    return (
      <div className="flex items-center justify-center p-8 bg-slate-50 text-slate-400 text-xs gap-2">
        <LoadingSpinner size="sm" />
        <span>Loading screenshot...</span>
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-4 bg-slate-50 border border-slate-200 rounded-lg text-center text-xs text-slate-500">
        <Camera className="w-4 h-4 mx-auto mb-1 text-slate-400" />
        <span className="font-medium text-slate-600 block">Screenshot unavailable</span>
        <span className="text-[11px] text-slate-400 mt-0.5 block">{error}</span>
      </div>
    );
  }

  if (!blobUrl) {
    return null;
  }

  return <img src={blobUrl} alt={alt} className={className} />;
};

export const AuthenticatedVideo: React.FC<AuthenticatedMediaProps> = ({
  artifactId,
  filePath,
  className = '',
}) => {
  const [blobUrl, setBlobUrl] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!artifactId && !filePath) {
      setBlobUrl(null);
      setError(null);
      setLoading(false);
      return;
    }

    let isMounted = true;
    let currentObjectUrl: string | null = null;

    setLoading(true);
    setError(null);

    reportsApi
      .fetchArtifactBlob({ id: artifactId, path: filePath })
      .then((blob) => {
        if (isMounted) {
          currentObjectUrl = URL.createObjectURL(blob);
          setBlobUrl(currentObjectUrl);
          setLoading(false);
        }
      })
      .catch((err: unknown) => {
        if (isMounted) {
          const message = err instanceof Error ? err.message : 'Failed to load video';
          setError(message);
          setLoading(false);
        }
      });

    return () => {
      isMounted = false;
      if (currentObjectUrl) {
        URL.revokeObjectURL(currentObjectUrl);
      }
    };
  }, [artifactId, filePath]);

  if (loading) {
    return (
      <div className="flex items-center justify-center p-12 bg-black text-slate-400 text-xs gap-2">
        <LoadingSpinner size="sm" />
        <span>Loading browser recording...</span>
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-6 bg-slate-900 border border-slate-800 rounded-lg text-center text-xs text-slate-400">
        <Film className="w-5 h-5 mx-auto mb-2 text-slate-500" />
        <p className="font-medium text-slate-300">Recording unavailable</p>
        <p className="text-[11px] text-slate-500 mt-1">{error}</p>
      </div>
    );
  }

  if (!blobUrl) {
    return null;
  }

  return (
    <video controls className={className} src={blobUrl}>
      Your browser does not support the video tag.
    </video>
  );
};
