package com.example.demo.service;

import org.springframework.stereotype.Service;

import com.example.demo.entity.Learner;
import com.example.demo.repository.LearnerRepository;

import org.springframework.beans.factory.annotation.Autowired;

import com.example.demo.entity.Cohort;
import com.example.demo.repository.CohortRepository;

import java.util.Optional;

import com.example.demo.exception.CohortNotFound;
import com.example.demo.exception.LearnerNotFound;

import java.util.List;

import com.example.demo.dto.LearnerDTO;
import com.example.demo.dto.CohortDTO;

import java.util.ArrayList;

import org.springframework.data.domain.Page;
import org.springframework.data.domain.PageImpl;
import org.springframework.data.domain.PageRequest;
import org.springframework.data.domain.Sort;

@Service
public class LearnerManagementService {

    @Autowired
    private LearnerRepository _learnerRepository;
    
    @Autowired
    private CohortRepository _cohortRepository;


    public List<LearnerDTO> getLearners() {
    
        List<Learner> learners = _learnerRepository.findAll();

        List<LearnerDTO> learnerDTOs = new ArrayList<>();

        for( Learner learner : learners ) {

            LearnerDTO learnerDTO = new LearnerDTO();

            learnerDTO.setLearnerId(learner.getLearnerId());
            learnerDTO.setLearnerName(learner.getLearnerName());
            learnerDTO.setLearnerEmail(learner.getLearnerEmail());

            List<CohortDTO> cohortDTOs = new ArrayList<>();

            for( Cohort cohort : learner.getCohorts() ) {

                CohortDTO cohortDTO = new CohortDTO();
                
                cohortDTO.setCohortId(cohort.getCohortId());
                cohortDTO.setCohortName(cohort.getCohortName());
                cohortDTO.setCohortDescription(cohort.getCohortDescription());

                cohortDTOs.add(cohortDTO);
            }

            learnerDTO.setCohorts(cohortDTOs);
            learnerDTOs.add(learnerDTO);

        }

        return learnerDTOs;
    }

    public Learner createLearner(Learner learner) {
        return _learnerRepository.save(learner);
    }

    public Cohort createCohort(Cohort cohort) {
        // Implement the logic to save the cohort to the database
        // For example, you can use a CohortRepository to save the cohort
        // return _cohortRepository.save(cohort);
        return _cohortRepository.save(cohort);
    }

    public Cohort assignLearnerToCohort(long learnerId, long cohortId) throws CohortNotFound , LearnerNotFound {
        // Implement the logic to assign the learner to the cohort
        // For example, you can retrieve the learner and cohort from the database,
        // update the learner's cohort field, and save it back to the database
        Optional<Cohort> cohortOptional = _cohortRepository.findById(cohortId);

        if(!cohortOptional.isPresent()) {
            throw new CohortNotFound("Cohort not found with id: " + cohortId);
        } 

        Cohort fetchedCohort = cohortOptional.get();

        Optional<Learner> learnerOptional = _learnerRepository.findById(learnerId);

        if(!learnerOptional.isPresent()) {
            throw new LearnerNotFound("Learner not found with id: " + learnerId);
        } 

        Learner fetchedLearner = learnerOptional.get();

        // Update the learner's cohort field and save it back to the database
        fetchedCohort.getLearners().add(fetchedLearner);

        return _cohortRepository.save(fetchedCohort);
    
    }

    public Cohort assignLearnersToCohort(long cohortId, List<Long> learnerIds) throws CohortNotFound, LearnerNotFound {

        Optional<Cohort> cohortOptional = _cohortRepository.findById(cohortId);

        if(!cohortOptional.isPresent()) {
            throw new CohortNotFound("Cohort not found with id: " + cohortId);
        }

        Cohort fetchedCohort = cohortOptional.get();

        List<Learner> learnersToAssign = new ArrayList<>();
        List<Learner> learnersExisting = fetchedCohort.getLearners();

        for( Long id : learnerIds ) {

            Optional<Learner> learnerOptional = _learnerRepository.findById(id);

            if( !learnerOptional.isPresent() ) {
                throw new LearnerNotFound("Learner not found with id: " + id);
            }

            if( learnersExisting.contains(learnerOptional.get()) ) {
                continue;
            }

            learnersToAssign.add(learnerOptional.get());
            
        }

        fetchedCohort.getLearners().addAll(learnersToAssign);

        return _cohortRepository.save(fetchedCohort);
 
    }

    public List<Cohort> fetchAllCohorts() {
        // Implement the logic to retrieve all cohorts from the database
        // For example, you can use a CohortRepository to fetch all cohorts
        return _cohortRepository.findAll();
    }

    public Page<LearnerDTO> fetchPaginatedLearners(int pageNumber, int pageSize, String sortBy, String sortDirection)
    {
        Sort.Direction direction;
        if(sortDirection.equals("asc")){
            direction = Sort.Direction.ASC;
        }
        else
        {
            direction = Sort.Direction.DESC;
        }

        Sort sort = Sort.by(direction, sortBy);
        PageRequest pageRequest = PageRequest.of(pageNumber, pageSize, sort);
        Page<Learner> pageLearner =  _learnerRepository.findAll(pageRequest);

         List<Learner> learners = pageLearner.getContent();
    
    // Step 2: Create a list to hold the DTOs
    List<LearnerDTO> learnerDTOs = new ArrayList<>();
    
    // Step 3: Loop through each learner and convert to DTO
    for(Learner learner : learners) {
        LearnerDTO dto = new LearnerDTO();
        dto.setLearnerId(learner.getLearnerId());
        dto.setLearnerName(learner.getLearnerName());
        dto.setLearnerEmail(learner.getLearnerEmail());
        
        // If you want cohorts too:
        List<CohortDTO> cohortDTOs = new ArrayList<>();
        for(Cohort cohort : learner.getCohorts()) {
            CohortDTO cohortDTO = new CohortDTO();
            cohortDTO.setCohortId(cohort.getCohortId());
            cohortDTO.setCohortName(cohort.getCohortName());
            cohortDTO.setCohortDescription(cohort.getCohortDescription());
            cohortDTOs.add(cohortDTO);
        }
        dto.setCohorts(cohortDTOs);
        
         learnerDTOs.add(dto);
    }
    
    // Step 4: Create a new Page with the DTOs and copy the page information
    Page<LearnerDTO> pageLearnerDTO = new PageImpl<>(
        learnerDTOs,           // The converted list
        pageRequest,           // Same page request (page number, size, sort)
        pageLearner.getTotalElements()  // Total count from original page
    );
    
    return pageLearnerDTO;
    }
}
