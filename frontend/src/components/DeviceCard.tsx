import React from 'react';

interface DeviceCardProps {
  id: string;
  model: string;
  status: string;
  isInitialized: boolean;
  isActive: boolean;
  onClick: () => void;
}

export function DeviceCard({
  id,
  model,
  status,
  isInitialized,
  isActive,
  onClick,
}: DeviceCardProps) {
  const isOnline = status === 'device';

  return (
    <button
      onClick={onClick}
      className={`w-full text-left px-4 py-3 rounded-lg transition-all ${
        isActive
          ? 'bg-blue-500 text-white shadow-md'
          : 'bg-white dark:bg-gray-800 hover:bg-gray-50 dark:hover:bg-gray-700'
      }`}
    >
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-3 min-w-0 flex-1">
          {/* 状态指示器 */}
          <div
            className={`w-2.5 h-2.5 rounded-full flex-shrink-0 ${
              isOnline
                ? 'bg-green-400 shadow-[0_0_4px_rgba(74,222,128,0.6)]'
                : 'bg-gray-400'
            }`}
            title={isOnline ? '在线' : '离线'}
          />

          <div className="min-w-0 flex-1">
            {/* 设备型号 */}
            <div
              className={`font-medium text-sm truncate ${
                isActive ? 'text-white' : 'text-gray-900 dark:text-gray-100'
              }`}
            >
              {model || '未知设备'}
            </div>

            {/* 设备 ID */}
            <div
              className={`text-xs truncate ${
                isActive ? 'text-blue-100' : 'text-gray-500 dark:text-gray-400'
              }`}
            >
              {id}
            </div>
          </div>
        </div>

        {/* 初始化状态标识 */}
        {isInitialized && (
          <div
            className={`flex-shrink-0 w-5 h-5 rounded-full flex items-center justify-center ${
              isActive ? 'bg-white/20' : 'bg-green-100 dark:bg-green-900'
            }`}
          >
            <svg
              className={`w-3 h-3 ${
                isActive ? 'text-white' : 'text-green-600 dark:text-green-400'
              }`}
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M5 13l4 4L19 7"
              />
            </svg>
          </div>
        )}
      </div>
    </button>
  );
}
