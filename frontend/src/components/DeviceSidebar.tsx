import React, { useState, useEffect } from 'react';
import {
  Smartphone,
  Settings,
  ChevronLeft,
  ChevronRight,
  Plug,
  Plus,
  Info,
} from 'lucide-react';
import { DeviceCard } from './DeviceCard';
import { Button } from '@/components/ui/button';
import { Separator } from '@/components/ui/separator';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '@/components/ui/dialog';
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import type { Device } from '../api';
import { connectWifiManual } from '../api';
import { useTranslation } from '../lib/i18n-context';

const getInitialCollapsedState = (): boolean => {
  try {
    const saved = localStorage.getItem('sidebar-collapsed');
    return saved !== null ? JSON.parse(saved) : false;
  } catch (error) {
    console.warn('Failed to load sidebar collapsed state:', error);
    return false;
  }
};

interface DeviceSidebarProps {
  devices: Device[];
  currentDeviceId: string;
  onSelectDevice: (deviceId: string) => void;
  onOpenConfig: () => void;
  onConnectWifi: (deviceId: string) => void;
  onDisconnectWifi: (deviceId: string) => void;
}

export function DeviceSidebar({
  devices,
  currentDeviceId,
  onSelectDevice,
  onOpenConfig,
  onConnectWifi,
  onDisconnectWifi,
}: DeviceSidebarProps) {
  const t = useTranslation();
  const [isCollapsed, setIsCollapsed] = useState(getInitialCollapsedState);

  // Manual WiFi connection
  const [showManualConnect, setShowManualConnect] = useState(false);
  const [manualConnectIp, setManualConnectIp] = useState('');
  const [manualConnectPort, setManualConnectPort] = useState('5555');
  const [ipError, setIpError] = useState('');
  const [portError, setPortError] = useState('');
  const [isConnecting, setIsConnecting] = useState(false);

  useEffect(() => {
    localStorage.setItem('sidebar-collapsed', JSON.stringify(isCollapsed));
  }, [isCollapsed]);

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key === 'b') {
        event.preventDefault();
        setIsCollapsed(!isCollapsed);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isCollapsed]);

  const toggleCollapse = () => {
    setIsCollapsed(!isCollapsed);
  };

  // Validation helpers
  const validateIp = (ip: string): boolean => {
    const ipPattern = /^(?:[0-9]{1,3}\.){3}[0-9]{1,3}$/;
    if (!ipPattern.test(ip)) return false;
    const parts = ip.split('.');
    return parts.every(part => {
      const num = parseInt(part, 10);
      return num >= 0 && num <= 255;
    });
  };

  const validatePort = (port: string): boolean => {
    const num = parseInt(port, 10);
    return !isNaN(num) && num >= 1 && num <= 65535;
  };

  const handleManualConnect = async () => {
    setIpError('');
    setPortError('');

    let hasError = false;

    if (!validateIp(manualConnectIp)) {
      setIpError(t.deviceSidebar.invalidIpError);
      hasError = true;
    }

    if (!validatePort(manualConnectPort)) {
      setPortError(t.deviceSidebar.invalidPortError);
      hasError = true;
    }

    if (hasError) return;

    setIsConnecting(true);
    try {
      const result = await connectWifiManual({
        ip: manualConnectIp,
        port: parseInt(manualConnectPort, 10),
      });

      if (result.success) {
        setShowManualConnect(false);
        setManualConnectIp('');
        setManualConnectPort('5555');
        // Device list will auto-refresh via polling
      } else {
        setIpError(result.message || t.toasts.wifiManualConnectError);
      }
    } catch {
      setIpError(t.toasts.wifiManualConnectError);
    } finally {
      setIsConnecting(false);
    }
  };

  return (
    <>
      {/* Collapsed toggle button */}
      {isCollapsed && (
        <Button
          variant="outline"
          size="icon"
          onClick={toggleCollapse}
          className="fixed left-0 top-20 z-50 h-16 w-8 rounded-r-lg rounded-l-none border-l-0 bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 dark:hover:bg-slate-700"
          title="Expand sidebar"
          style={{ left: 0 }}
        >
          <ChevronRight className="h-4 w-4" />
        </Button>
      )}

      {/* Sidebar */}
      <div
        className={`
          ${isCollapsed ? 'w-0 -ml-4 opacity-0' : 'w-80 opacity-100'}
          transition-all duration-300 ease-in-out
          h-full min-h-0
          bg-white dark:bg-slate-950
          border-r border-slate-200 dark:border-slate-800
          flex flex-col
          overflow-hidden
        `}
      >
        {/* Header */}
        <div className="flex items-center justify-between p-4">
          <div className="flex items-center gap-2">
            <div className="flex h-10 w-10 items-center justify-center rounded-full bg-[#1d9bf0]/10">
              <Smartphone className="h-5 w-5 text-[#1d9bf0]" />
            </div>
            <div>
              <h2 className="text-base font-bold text-slate-900 dark:text-slate-100">
                AutoGLM
              </h2>
              <p className="text-xs text-slate-500 dark:text-slate-400">
                {devices.length}{' '}
                {devices.length === 1
                  ? t.deviceSidebar.devices
                  : t.deviceSidebar.devices}
              </p>
            </div>
          </div>

          <Button
            variant="ghost"
            size="icon"
            onClick={toggleCollapse}
            className="h-8 w-8 rounded-full text-slate-400 hover:text-slate-600 dark:text-slate-500 dark:hover:text-slate-300"
            title="Collapse sidebar"
          >
            <ChevronLeft className="h-4 w-4" />
          </Button>
        </div>

        <Separator className="mx-4" />

        {/* Device list */}
        <div className="flex-1 overflow-y-auto p-3 space-y-2 min-h-0">
          {devices.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-center">
              <div className="flex h-16 w-16 items-center justify-center rounded-full bg-slate-100 dark:bg-slate-800">
                <Plug className="h-8 w-8 text-slate-400" />
              </div>
              <p className="mt-4 font-medium text-slate-900 dark:text-slate-100">
                {t.deviceSidebar.noDevicesConnected}
              </p>
              <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
                {t.deviceSidebar.clickToRefresh}
              </p>
            </div>
          ) : (
            devices.map(device => (
              <DeviceCard
                key={device.id}
                id={device.id}
                model={device.model}
                status={device.status}
                connectionType={device.connection_type}
                isInitialized={device.is_initialized}
                isActive={currentDeviceId === device.id}
                onClick={() => onSelectDevice(device.id)}
                onConnectWifi={async () => {
                  await onConnectWifi(device.id);
                }}
                onDisconnectWifi={async () => {
                  await onDisconnectWifi(device.id);
                }}
              />
            ))
          )}
        </div>

        <Separator className="mx-4" />

        {/* Bottom actions */}
        <div className="p-3 space-y-2">
          <Button
            variant="outline"
            onClick={() => setShowManualConnect(true)}
            className="w-full justify-start gap-2 rounded-full border-slate-200 dark:border-slate-700"
          >
            <Plus className="h-4 w-4" />
            <span className="flex-1 text-left">
              {t.deviceSidebar.addDevice}
            </span>
            <Tooltip>
              <TooltipTrigger asChild>
                <div>
                  <Info className="h-3.5 w-3.5 text-slate-400 flex-shrink-0" />
                </div>
              </TooltipTrigger>
              <TooltipContent
                side="right"
                align="center"
                sideOffset={5}
                className="max-w-xs"
              >
                <p>{t.deviceSidebar.addDeviceTooltip}</p>
              </TooltipContent>
            </Tooltip>
          </Button>
          <Button
            variant="outline"
            onClick={onOpenConfig}
            className="w-full justify-start gap-2 rounded-full border-slate-200 dark:border-slate-700"
          >
            <Settings className="h-4 w-4" />
            {t.deviceSidebar.settings}
          </Button>
        </div>

        {/* Manual WiFi Connect Dialog */}
        <Dialog open={showManualConnect} onOpenChange={setShowManualConnect}>
          <DialogContent className="sm:max-w-md">
            <DialogHeader>
              <DialogTitle>{t.deviceSidebar.manualConnectTitle}</DialogTitle>
              <DialogDescription>
                {t.deviceSidebar.manualConnectDescription}
              </DialogDescription>
            </DialogHeader>
            <div className="space-y-4 py-4">
              <div className="space-y-2">
                <Label htmlFor="ip">{t.deviceSidebar.ipAddress}</Label>
                <Input
                  id="ip"
                  placeholder="192.168.1.100"
                  value={manualConnectIp}
                  onChange={e => setManualConnectIp(e.target.value)}
                  onKeyDown={e => e.key === 'Enter' && handleManualConnect()}
                  className={ipError ? 'border-red-500' : ''}
                />
                {ipError && <p className="text-sm text-red-500">{ipError}</p>}
              </div>
              <div className="space-y-2">
                <Label htmlFor="port">{t.deviceSidebar.port}</Label>
                <Input
                  id="port"
                  type="number"
                  value={manualConnectPort}
                  onChange={e => setManualConnectPort(e.target.value)}
                  onKeyDown={e => e.key === 'Enter' && handleManualConnect()}
                  className={portError ? 'border-red-500' : ''}
                />
                {portError && (
                  <p className="text-sm text-red-500">{portError}</p>
                )}
              </div>
            </div>
            <DialogFooter>
              <Button
                variant="outline"
                onClick={() => {
                  setShowManualConnect(false);
                  setIpError('');
                  setPortError('');
                }}
              >
                {t.common.cancel}
              </Button>
              <Button onClick={handleManualConnect} disabled={isConnecting}>
                {isConnecting ? t.common.loading : t.common.confirm}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </div>
    </>
  );
}
