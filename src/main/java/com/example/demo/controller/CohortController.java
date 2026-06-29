package com.example.demo.controller;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import com.example.demo.entity.Cohort;
import com.example.demo.entity.LearnerListBody;
import java.util.List;
import com.example.demo.exception.CohortNotFound;
import com.example.demo.exception.LearnerNotFound;
import com.example.demo.service.LearnerManagementService;


@RestController
public class CohortController {

    @Autowired
    private LearnerManagementService _learnerManagementService;


    @PostMapping("/cohorts")
    public Cohort createCohort(@RequestBody Cohort cohort) {
        return _learnerManagementService.createCohort(cohort);
    }

    @PostMapping("/assignLearnerToCohort")
    public Cohort assignLearnerToCohort(@RequestParam long learnerId, @RequestParam long cohortId) throws CohortNotFound, LearnerNotFound {
        // Implement the logic to assign the learner to the cohort
        // For example, you can update the learner's cohort field and save it to the database
        // return "Learner assigned to cohort successfully";

        return _learnerManagementService.assignLearnerToCohort(learnerId, cohortId);
    
    }

    @GetMapping("/cohorts")
    public List<Cohort> fetchAllCohorts() {
        // Implement the logic to retrieve a cohort from the database
        // For example, you can use a CohortRepository to fetch the cohort by ID
        // return _cohortRepository.findById(cohortId).orElse(null);
        return _learnerManagementService.fetchAllCohorts(); // Replace with the actual logic to fetch a cohort
    }

    @PostMapping("/cohorts/{cohortId}/learners")
    public Cohort assignLearnersToCohort( @PathVariable long cohortId, @RequestBody LearnerListBody learnerIds) 
        throws CohortNotFound, LearnerNotFound {
        return _learnerManagementService.assignLearnersToCohort(cohortId, learnerIds.getLearnerIds());
    }

}
