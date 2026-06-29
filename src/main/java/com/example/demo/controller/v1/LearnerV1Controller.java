package com.example.demo.controller.v1;

import org.springframework.web.bind.annotation.RestController;
import org.springframework.beans.factory.annotation.Autowired;

import com.example.demo.dto.LearnerDTO;
import com.example.demo.service.LearnerManagementService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.data.domain.Page;
import com.example.demo.entity.Learner;


@RestController
public class LearnerV1Controller {

    @Autowired
    private LearnerManagementService _learnerManagementService;

    @GetMapping("/v1/learners")
    public Page<LearnerDTO> getPaginatedLearners(
        @RequestParam(defaultValue = "0") int pageNumber,
        @RequestParam(defaultValue = "10") int pageSize,
        @RequestParam(defaultValue = "learnerId") String sortBy,
        @RequestParam(defaultValue = "asc") String sortDirection) {
            return _learnerManagementService.fetchPaginatedLearners(pageNumber, pageSize, sortBy, sortDirection);
        }
}
