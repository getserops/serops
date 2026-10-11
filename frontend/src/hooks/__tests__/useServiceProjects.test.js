/**
 * Tests for useServiceProjects hook
 * 
 * Tests:
 * - Initial state values
 * - Form handling
 * - Validation logic
 * - Modal state management
 */

import { describe, it, expect, vi, beforeEach, test } from 'vitest';
import { renderHook, act, waitFor } from '@testing-library/react';
import { useServiceProjects } from '../useServiceProjects';

// Mock the ProjectService
vi.mock('../../services/project.service', () => ({
    ProjectService: {
        GetProjectDetails: vi.fn(),
        GetProjectServices: vi.fn(),
        AddCustomService: vi.fn(),
        AddGitLabProjectAsService: vi.fn(),
        AddInfraService: vi.fn(),
        DeleteProjectService: vi.fn(),
        VerifyGitLabProject: vi.fn(),
        GetGitLabProjectDetails: vi.fn(),
    },
}));

// Mock localStorage
const localStorageMock = (() => {
    let store = {};
    return {
        getItem: vi.fn((key) => store[key] || null),
        setItem: vi.fn((key, value) => { store[key] = value.toString(); }),
        clear: vi.fn(() => { store = {}; }),
        removeItem: vi.fn((key) => { delete store[key]; }),
    };
})();

Object.defineProperty(window, 'localStorage', {
    value: localStorageMock,
    writable: true,
});

import { ProjectService } from '../../services/project.service';

describe('useServiceProjects', () => {
    const mockProjectId = '123';
    const mockProjectName = 'Test Project';
    const mockServices = [
        { id: 1, name: 'Service 1', status: 'Active', service_type: 'custom' },
        { id: 2, name: 'Service 2', status: 'Active', service_type: 'gitlab' },
    ];

    beforeEach(() => {
        vi.clearAllMocks();
        // Mock localStorage.getItem to return token
        window.localStorage.getItem.mockReturnValue('test-token');

        // Default mock implementations
        ProjectService.GetProjectDetails.mockResolvedValue({ name: mockProjectName });
        ProjectService.GetProjectServices.mockResolvedValue(mockServices);
    });

    describe('Initial State', () => {
        it('should start with loading true', () => {
            const { result } = renderHook(() => useServiceProjects(mockProjectId));
            expect(result.current.loading).toBe(true);
        });

        it('should have empty form data initially', () => {
            const { result } = renderHook(() => useServiceProjects(mockProjectId));
            expect(result.current.formData.name).toBe('');
            // INITIAL_FORM_DATA defaults to 'application'. This asserted
            // 'custom', the default before the polymorphic service types
            // landed, so it described a form state the hook never produces.
            expect(result.current.formData.service_type).toBe('application');
        });

        it('should have modal closed initially', () => {
            const { result } = renderHook(() => useServiceProjects(mockProjectId));
            expect(result.current.showModal).toBe(false);
            expect(result.current.showDetailsModal).toBe(false);
        });
    });

    describe('Data Fetching', () => {
        it('should fetch project details on mount', async () => {
            const { result } = renderHook(() => useServiceProjects(mockProjectId));

            await waitFor(() => {
                expect(result.current.loading).toBe(false);
            });

            expect(ProjectService.GetProjectDetails).toHaveBeenCalledWith(mockProjectId);
            expect(result.current.projectName).toBe(mockProjectName);
        });

        it('should fetch services on mount', async () => {
            const { result } = renderHook(() => useServiceProjects(mockProjectId));

            await waitFor(() => {
                expect(result.current.loading).toBe(false);
            });

            expect(ProjectService.GetProjectServices).toHaveBeenCalledWith(mockProjectId);
            expect(result.current.services).toHaveLength(2);
        });
    });

    describe('Modal Handling', () => {
        it('should open modal and reset form', async () => {
            const { result } = renderHook(() => useServiceProjects(mockProjectId));

            await waitFor(() => expect(result.current.loading).toBe(false));

            act(() => {
                result.current.handleOpenModal();
            });

            expect(result.current.showModal).toBe(true);
            expect(result.current.submitError).toBeNull();
            expect(result.current.formData.name).toBe('');
        });

        it('should close modal and clear errors', async () => {
            const { result } = renderHook(() => useServiceProjects(mockProjectId));

            await waitFor(() => expect(result.current.loading).toBe(false));

            act(() => {
                result.current.handleOpenModal();
            });

            act(() => {
                result.current.handleCloseModal();
            });

            expect(result.current.showModal).toBe(false);
            expect(result.current.submitError).toBeNull();
        });
    });

    describe('Form Handling', () => {
        it('should update form data on change', async () => {
            const { result } = renderHook(() => useServiceProjects(mockProjectId));

            await waitFor(() => expect(result.current.loading).toBe(false));

            act(() => {
                result.current.handleChange({
                    target: { name: 'name', value: 'New Service' }
                });
            });

            expect(result.current.formData.name).toBe('New Service');
        });

        it('should clear submit error on form change', async () => {
            const { result } = renderHook(() => useServiceProjects(mockProjectId));

            await waitFor(() => expect(result.current.loading).toBe(false));

            // Set error first (would normally come from failed submit)
            act(() => {
                result.current.handleOpenModal();
            });

            act(() => {
                result.current.handleChange({
                    target: { name: 'name', value: 'Test' }
                });
            });

            expect(result.current.submitError).toBeNull();
        });
    });

    describe('Validation', () => {
        it('should require name for custom service', async () => {
            const { result } = renderHook(() => useServiceProjects(mockProjectId));

            await waitFor(() => expect(result.current.loading).toBe(false));

            act(() => {
                result.current.handleOpenModal();
                // Must select the custom type: validation branches on
                // service_type, and the default is 'application', whose
                // first required field is the project ID. Without this the
                // test exercised the application branch and asserted the
                // custom branch's message.
                result.current.setFormData(prev => ({ ...prev, service_type: 'custom' }));
            });

            // Try to submit without name
            await act(async () => {
                await result.current.handleSubmit();
            });

            expect(result.current.submitError).toBe('Service name is required');
        });

        it('should require authentication for submit', async () => {
            // Mock no token
            window.localStorage.getItem.mockReturnValue(null);
            const { result } = renderHook(() => useServiceProjects(mockProjectId));

            await waitFor(() => expect(result.current.loading).toBe(false));

            await act(async () => {
                await result.current.handleSubmit();
            });

            expect(result.current.submitError).toContain('logged in');
        });
    });

    describe('Pagination', () => {
        it('should paginate services correctly', async () => {
            // Mock 10 services for pagination test
            const manyServices = Array.from({ length: 10 }, (_, i) => ({
                id: i + 1,
                name: `Service ${i + 1}`,
                status: 'Active',
            }));
            ProjectService.GetProjectServices.mockResolvedValue(manyServices);

            const { result } = renderHook(() => useServiceProjects(mockProjectId));

            await waitFor(() => expect(result.current.loading).toBe(false));

            // Default page size is 5, so should have 2 pages
            expect(result.current.totalPages).toBe(2);
            expect(result.current.services).toHaveLength(5); // First page
        });

        it('should change page correctly', async () => {
            const manyServices = Array.from({ length: 10 }, (_, i) => ({
                id: i + 1,
                name: `Service ${i + 1}`,
                status: 'Active',
            }));
            ProjectService.GetProjectServices.mockResolvedValue(manyServices);

            const { result } = renderHook(() => useServiceProjects(mockProjectId));

            await waitFor(() => expect(result.current.loading).toBe(false));

            act(() => {
                result.current.goToPage(2);
            });

            expect(result.current.currentPage).toBe(2);
        });

        it('should not go to invalid page', async () => {
            const { result } = renderHook(() => useServiceProjects(mockProjectId));

            await waitFor(() => expect(result.current.loading).toBe(false));

            act(() => {
                result.current.goToPage(0);
            });

            expect(result.current.currentPage).toBe(1);

            act(() => {
                result.current.goToPage(999);
            });

            expect(result.current.currentPage).toBe(1);
        });
    });

    describe('Service Operations', () => {
        it('should add custom service successfully', async () => {
            ProjectService.AddCustomService.mockResolvedValue({ id: 3, name: 'New Service' });

            const { result } = renderHook(() => useServiceProjects(mockProjectId));

            await waitFor(() => expect(result.current.loading).toBe(false));

            act(() => {
                result.current.handleOpenModal();
                // service_type must be 'custom' for AddCustomService to be
                // the call under test; the default 'application' routes to
                // a different service method entirely.
                result.current.setFormData(prev => ({
                    ...prev, name: 'New Service', service_type: 'custom',
                }));
            });

            await act(async () => {
                await result.current.handleSubmit();
            });

            expect(ProjectService.AddCustomService).toHaveBeenCalled();
            expect(result.current.submitSuccess).toBe(true);
        });

        it('should delete service and refresh list', async () => {
            // Mock window.confirm
            vi.spyOn(window, 'confirm').mockReturnValue(true);
            ProjectService.DeleteProjectService.mockResolvedValue({});

            const { result } = renderHook(() => useServiceProjects(mockProjectId));

            await waitFor(() => expect(result.current.loading).toBe(false));

            await act(async () => {
                await result.current.handleDelete(1);
            });

            expect(ProjectService.DeleteProjectService).toHaveBeenCalledWith(1);
            expect(ProjectService.GetProjectServices).toHaveBeenCalledTimes(2); // Initial + refresh
        });
    });
});
