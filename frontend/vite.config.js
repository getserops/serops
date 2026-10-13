import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const isAnalyze = process.env.ANALYZE === 'true';

// https://vitejs.dev/config/
export default defineConfig({
    plugins: [
        react(),
        // Only load visualizer when explicitly requested (ANALYZE=true npm run build)
        isAnalyze && import('rollup-plugin-visualizer').then(m => m.visualizer({
            filename: './dist/stats.html',
            open: false,
            gzipSize: true,
            brotliSize: true,
        })),
    ].filter(Boolean),
    server: {
        host: true,
        port: 3003,
        proxy: {
            '/api': {
                target: 'http://backend:8000',
                changeOrigin: true,
                secure: false,
            }
        }
    },
    test: {
        globals: true,
        environment: 'happy-dom',
        setupFiles: ['./src/test/setup.js'],
        include: ['src/**/*.{test,spec}.{js,jsx,ts,tsx}'],
    },
    build: {
        sourcemap: false,
        rollupOptions: {
            output: {
                manualChunks: {
                    'react-vendor': ['react', 'react-dom', 'react-router-dom'],
                    'ui-bootstrap': ['bootstrap', 'react-bootstrap', 'reactstrap'],
                    'ui-mui': ['@mui/material', '@emotion/react', '@emotion/styled'],
                    'ui-antd': ['antd'],
                    'query-vendor': ['@tanstack/react-query'],
                    'charts-vendor': ['recharts'],
                    'icons': ['react-icons', 'lucide-react'],
                    'i18n': ['i18next', 'react-i18next', 'i18next-browser-languagedetector'],
                    'motion': ['framer-motion'],
                }
            }
        },
        chunkSizeWarningLimit: 1000,
    }
})
