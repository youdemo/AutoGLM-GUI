import React, { useState } from 'react';
import { Wifi, WifiOff, CheckCircle2, Smartphone, Loader2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { ConfirmDialog } from './ConfirmDialog';
import { useTranslation } from '../lib/i18n-context';

interface DeviceCardProps {
  id: string;
  model: string;
  status: string;
  connectionType?: string;
  isInitialized: boolean;
  isActive: boolean;
  onClick: () => void;
  onConnectWifi?: () => Promise<void>;
  onDisconnectWifi?: () => Promise<void>;
}

export function DeviceCard({
  id,
  model,
  status,
  connectionType,
  isInitialized,
  isActive,
  onClick,
  onConnectWifi,
  onDisconnectWifi,
}: DeviceCardProps) {
  const t = useTranslation();
  const isOnline = status === 'device';
  const isUsb = connectionType === 'usb';
  const isRemote = connectionType === 'remote';
  const [loading, setLoading] = useState(false);
  const [showWifiConfirm, setShowWifiConfirm] = useState(false);
  const [showDisconnectConfirm, setShowDisconnectConfirm] = useState(false);

  const handleWifiClick = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (loading || !onConnectWifi) return;
    setShowWifiConfirm(true);
  };

  const handleDisconnectClick = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (loading || !onDisconnectWifi) return;
    setShowDisconnectConfirm(true);
  };

  const handleConfirmWifi = async () => {
    setShowWifiConfirm(false);
    setLoading(true);
    try {
      if (onConnectWifi) {
        await onConnectWifi();
      }
    } finally {
      setLoading(false);
    }
  };

  const handleConfirmDisconnect = async () => {
    setShowDisconnectConfirm(false);
    setLoading(true);
    try {
      if (onDisconnectWifi) {
        await onDisconnectWifi();
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <>
      <div
        onClick={onClick}
        role="button"
        tabIndex={0}
        onKeyDown={e => {
          if (e.key === 'Enter' || e.key === ' ') {
            onClick();
          }
        }}
        className={`
          group relative w-full text-left p-4 rounded-xl transition-all duration-200 cursor-pointer
          border-2
          ${
            isActive
              ? 'bg-slate-50 border-[#1d9bf0] dark:bg-slate-800/50 dark:border-[#1d9bf0]'
              : 'bg-white border-transparent hover:border-slate-200 dark:bg-slate-900 dark:hover:border-slate-700'
          }
        `}
      >
        {/* Active indicator bar */}
        {isActive && (
          <div className="absolute left-0 top-2 bottom-2 w-1 bg-[#1d9bf0] rounded-r" />
        )}

        <div className="flex items-center gap-3 pl-2">
          {/* Status indicator */}
          <div
            className={`relative flex-shrink-0 ${
              isOnline ? 'status-online' : 'status-offline'
            } w-3 h-3 rounded-full transition-all ${
              isActive ? 'scale-110' : ''
            }`}
          />

          {/* Device icon and info */}
          <div className="flex-1 min-w-0 flex flex-col justify-center gap-0.5">
            <div className="flex items-center gap-2">
              <Smartphone
                className={`w-4 h-4 ${
                  isActive
                    ? 'text-[#1d9bf0]'
                    : 'text-slate-400 dark:text-slate-500'
                }`}
              />
              <span
                className={`font-semibold text-sm truncate ${
                  isActive
                    ? 'text-slate-900 dark:text-slate-100'
                    : 'text-slate-700 dark:text-slate-300'
                }`}
              >
                {model || t.deviceCard.unknownDevice}
              </span>
            </div>
            <span
              className={`text-xs font-mono truncate ${
                isActive
                  ? 'text-slate-500 dark:text-slate-400'
                  : 'text-slate-400 dark:text-slate-500'
              }`}
            >
              {id}
            </span>
          </div>

          {/* Action buttons */}
          <div className="flex items-center gap-1">
            {isUsb && onConnectWifi && (
              <Button
                variant="ghost"
                size="icon"
                onClick={handleWifiClick}
                disabled={loading}
                className={`h-8 w-8 rounded-full ${
                  isActive
                    ? 'text-white hover:bg-white/20'
                    : 'text-slate-400 hover:text-[#1d9bf0] hover:bg-slate-100 dark:hover:bg-slate-800'
                }`}
                title={t.deviceCard.connectViaWifi}
              >
                {loading ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  <Wifi className="w-4 h-4" />
                )}
              </Button>
            )}

            {isRemote && onDisconnectWifi && (
              <Button
                variant="ghost"
                size="icon"
                onClick={handleDisconnectClick}
                disabled={loading}
                className={`h-8 w-8 rounded-full ${
                  isActive
                    ? 'text-white hover:bg-white/20'
                    : 'text-slate-400 hover:text-red-500 hover:bg-slate-100 dark:hover:bg-slate-800'
                }`}
                title={t.deviceCard.disconnectWifi}
              >
                {loading ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  <WifiOff className="w-4 h-4" />
                )}
              </Button>
            )}

            {/* Initialization status badge */}
            {isInitialized && (
              <Badge
                variant="success"
                className={`text-xs ${
                  isActive ? 'bg-white/20 text-white' : ''
                }`}
              >
                <CheckCircle2 className="w-3 h-3 mr-1" />
                {t.deviceCard.ready}
              </Badge>
            )}
          </div>
        </div>
      </div>

      <ConfirmDialog
        isOpen={showWifiConfirm}
        title={t.deviceCard.connectWifiTitle}
        content={t.deviceCard.connectWifiContent}
        onConfirm={handleConfirmWifi}
        onCancel={() => setShowWifiConfirm(false)}
      />

      <ConfirmDialog
        isOpen={showDisconnectConfirm}
        title={t.deviceCard.disconnectWifiTitle}
        content={t.deviceCard.disconnectWifiContent}
        onConfirm={handleConfirmDisconnect}
        onCancel={() => setShowDisconnectConfirm(false)}
      />
    </>
  );
}
